#!/usr/bin/env python3
"""
audio_spectrum.py -- a real audio-spectrum waterfall, alongside (not
replacing) the decode-based one in waterfall.js. WSJT-X's UDP API carries
no spectrum data at all, so this captures audio directly from the same
input device WSJT-X itself is configured to use and computes the FFT here.

Confirmed live (2026-08-01) this is safe: opening a second, independent
input stream on WSJT-X's configured device *while WSJT-X is actively
decoding* works immediately on this machine's hardware audio interface (a
real USB CODEC, not a virtual router) -- no permission prompt blocked it,
and WSJT-X kept decoding normally throughout, confirmed by watching new
ALL.TXT lines keep appearing on schedule during and after the test.

Params (agreed with the user): 48kHz samplerate, 12,000-sample (250ms) FFT
window -- gives exactly 4 Hz/bin (48000/12000), matching "4 Hz per pixel is
the most I'd need" for the 200 Hz-3 kHz band of interest. Two broadcast
rates: every block (spectrum_4hz, 4/sec) and a 4-block rolling average
(spectrum_1hz, ~1/sec) -- averaging in the linear-magnitude domain uses the
full second of audio instead of just one 250ms slice of it, so it's
noticeably less jumpy on bursty HF signals than a single raw snapshot.

No new Flask route for the data itself -- broadcasts over the existing
/live/ws feed via live_monitor.get_monitor().broadcast_event(), same shared
transport wsjtx_remote.py already reuses. Only /live/spectrum_status (see
live_monitor.py) exists to let the frontend show a clear message if no
matching audio device was found, rather than a silently blank panel.

Lazy since 2026-08-02: the input stream doesn't open at startup any more --
only device *resolution* (query_devices(), no audio actually captured)
happens eagerly in init_audio_spectrum(), so /live/spectrum_status can still
report a real error immediately. The stream itself only opens once at least
one browser client is actually viewing a spectrum mode, and closes again
once the last one stops -- see add_listener()/remove_listener() below, and
the "spectrum_listen"/"spectrum_unlisten" websocket actions in
live_monitor.py's /live/ws route, which call these based on which mode the
Waterfall tab / Remote tab's embedded panel currently has selected (and,
for the embedded panel, whether it's shown at all). Without this, the mic
stayed open and the FFT ran continuously for the life of the process
regardless of whether any browser tab was even looking at it.
"""

from __future__ import annotations

import collections
import logging
import os
import re
import threading
from typing import Optional

import numpy as np

import live_monitor

log = logging.getLogger("audio_spectrum")

try:
    import sounddevice as sd
    _SOUNDDEVICE_AVAILABLE = True
except ImportError:
    sd = None
    _SOUNDDEVICE_AVAILABLE = False

WSJTX_INI_PATH = os.path.expanduser("~/Library/Preferences/WSJT-X.ini")

# Matches "SoundInName=X" (the default/active configuration) as well as
# backend-scoped variants like "Flrig\Configuration\SoundInName=X" --
# WSJT-X stores a copy per rig-control backend so switching between them
# doesn't lose your audio settings. In practice (confirmed against this
# installation's real WSJT-X.ini) they all agree on the same device, but if
# they ever don't, the unprefixed/default one wins -- see
# _read_wsjtx_input_device_name.
_SOUND_IN_RE = re.compile(r'^(?:[\w]+\\Configuration\\)?SoundInName\s*=\s*(.*)$')


def _read_wsjtx_input_device_name(ini_path: str = WSJTX_INI_PATH) -> Optional[str]:
    try:
        with open(ini_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None
    candidates = []
    for raw in lines:
        line = raw.rstrip("\n").rstrip("\r")
        m = _SOUND_IN_RE.match(line)
        if not m:
            continue
        name = m.group(1).strip().strip('"').strip()
        if name:
            candidates.append((line.startswith("SoundInName"), name))
    if not candidates:
        return None
    for is_default, name in candidates:
        if is_default:
            return name
    return candidates[0][1]


def _find_input_device_index(name: str) -> Optional[int]:
    target = name.strip().lower()
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        if d.get("max_input_channels", 0) > 0 and d.get("name", "").strip().lower() == target:
            return i
    return None


class AudioSpectrum:
    SAMPLE_RATE = 48000
    BLOCK_SIZE = 12000  # 250ms @ 48kHz -- exactly 4 Hz/bin
    BIN_HZ = SAMPLE_RATE / BLOCK_SIZE  # 4.0
    START_HZ = 200
    END_HZ = 3000
    START_BIN = int(START_HZ / BIN_HZ)  # 50
    END_BIN = int(END_HZ / BIN_HZ)      # 750
    AVG_BLOCKS = 4  # -> ~1 update/sec from 4x 250ms blocks

    def __init__(self, device_name: Optional[str]):
        self.device_name = device_name
        self.device_index: Optional[int] = None
        self.error: Optional[str] = None
        self.stream = None
        self._window = np.hanning(self.BLOCK_SIZE).astype(np.float32)
        self._avg_buffer: collections.deque = collections.deque(maxlen=self.AVG_BLOCKS)
        self._block_count = 0
        self._listener_count = 0
        self._lock = threading.Lock()

    def resolve_device(self):
        """Validates sounddevice/device availability without opening the
        stream -- called once eagerly at startup so /live/spectrum_status
        can report a real error immediately, even with zero listeners
        (laziness only defers the actual audio capture, not error checks)."""
        if not _SOUNDDEVICE_AVAILABLE:
            self.error = "sounddevice is not installed (pip install sounddevice)"
            log.warning(self.error)
            return
        if not self.device_name:
            self.error = "Could not find WSJT-X's configured audio input device (SoundInName) in WSJT-X.ini"
            log.warning(self.error)
            return
        try:
            self.device_index = _find_input_device_index(self.device_name)
        except Exception as exc:
            self.error = f"Failed to enumerate audio devices: {exc}"
            log.exception(self.error)
            return
        if self.device_index is None:
            self.error = f"Audio input device {self.device_name!r} (WSJT-X's configured SoundInName) not found"
            log.warning(self.error)

    def _open_stream(self):
        if self.stream is not None or self.device_index is None:
            return
        # Fresh state each time capture (re)starts, so the 1Hz average
        # doesn't blend blocks from a previous listener session across
        # whatever gap of time it was closed for.
        self._avg_buffer.clear()
        self._block_count = 0
        try:
            self.stream = sd.InputStream(
                device=self.device_index, channels=1, samplerate=self.SAMPLE_RATE,
                blocksize=self.BLOCK_SIZE, dtype="float32", callback=self._on_audio,
            )
            self.stream.start()
            log.info("Audio spectrum capture started on %r (device %d)", self.device_name, self.device_index)
        except Exception as exc:
            self.error = f"Failed to open audio input stream: {exc}"
            log.exception(self.error)
            self.stream = None

    def add_listener(self):
        """Called when a browser client starts viewing a spectrum mode --
        opens the audio stream on the first listener, no-ops otherwise."""
        with self._lock:
            self._listener_count += 1
            if self._listener_count == 1:
                self._open_stream()

    def remove_listener(self):
        """Called when a browser client stops viewing a spectrum mode (mode
        switch, page close/navigate, or dropped connection) -- closes the
        audio stream once the last listener is gone."""
        with self._lock:
            if self._listener_count > 0:
                self._listener_count -= 1
            if self._listener_count == 0:
                self.stop()

    def stop(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
            log.info("Audio spectrum capture stopped (no listeners)")

    def _on_audio(self, indata, frames, time_info, status):
        if status:
            log.debug("sounddevice status: %s", status)
        try:
            samples = indata[:, 0]
            windowed = samples * self._window
            spectrum = np.abs(np.fft.rfft(windowed))
            bins = spectrum[self.START_BIN:self.END_BIN]

            self._broadcast("spectrum_4hz", bins)

            self._avg_buffer.append(bins)
            self._block_count += 1
            if self._block_count % self.AVG_BLOCKS == 0:
                avg_linear = np.mean(np.stack(self._avg_buffer), axis=0)
                self._broadcast("spectrum_1hz", avg_linear)
        except Exception:
            log.exception("Error processing audio block")

    def _broadcast(self, kind: str, linear_bins) -> None:
        monitor = live_monitor.get_monitor()
        if monitor is None:
            return
        db = 20 * np.log10(linear_bins + 1e-9)
        monitor.broadcast_event({
            "kind": kind,
            "bins": [round(float(v), 1) for v in db],
            "bin_hz": self.BIN_HZ,
            "start_hz": self.START_HZ,
        })

    def status(self) -> dict:
        return {
            "available": _SOUNDDEVICE_AVAILABLE,
            # False whenever nobody's listening -- that's the expected lazy
            # state, not an error. Check "error" for whether something's
            # actually wrong.
            "capturing": self.stream is not None and self.error is None,
            "device_name": self.device_name,
            "error": self.error,
            "listener_count": self._listener_count,
        }


_spectrum: Optional[AudioSpectrum] = None


def init_audio_spectrum():
    global _spectrum
    device_name = _read_wsjtx_input_device_name()
    _spectrum = AudioSpectrum(device_name)
    # Only resolves/validates the device -- doesn't open the audio stream.
    # That's deferred to the first add_listener() call, see module docstring.
    _spectrum.resolve_device()
    return _spectrum


def get_spectrum() -> Optional[AudioSpectrum]:
    """Accessor for live_monitor.py's /live/ws route, which calls
    add_listener()/remove_listener() based on "spectrum_listen"/
    "spectrum_unlisten" client messages."""
    return _spectrum


def status() -> dict:
    if _spectrum is None:
        return {"available": _SOUNDDEVICE_AVAILABLE, "capturing": False, "device_name": None, "error": "Not initialised"}
    return _spectrum.status()

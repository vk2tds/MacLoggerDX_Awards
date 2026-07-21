#!/usr/bin/env python3
"""
rigdial_bridge.py -- driver for a Contour ShuttleXpress USB HID controller
(5 buttons + jog wheel + shuttle ring), used as a hardware remote for the
"Radio" tab's rigctld connection (radio_control.py). No Flask here -- see
rigdial.py for the blueprint that wraps this.

Ported from the user's original standalone script (RigDial/rigdial.py),
which drove the radio via Flrig's XML-RPC interface. This version drives
radio_control.RigctldClient instead (the same rigctld connection the Radio
tab already uses), and generalizes the original's hardcoded button/jog/
shuttle behavior into a small named action set the user can reassign per
button via config, rather than fixed button indices in code.

HID report format (confirmed 2026-07-17 against the real device -- 5 bytes,
big-endian when hex-packed into one int, matching the bit masks below):
  byte0: shuttle ring position, low nibble, signed via wraparound (0x0-0x8
         = 0..8, 0x9-0xF = -7..-1)
  byte1: jog wheel absolute position, wraps 0-255 -- only the delta between
         reports matters
  byte2: unused
  byte3: buttons 0-3, one bit each (0x10/0x20/0x40/0x80)
  byte4: button 4 (0x01)

Native library note: the `hid` package (PyPI "hid", imports as `hid`) is a
ctypes wrapper around libhidapi -- it does NOT bundle the native library,
and its internal loader only tries bare filenames (e.g. "libhidapi.dylib"),
which only resolves if DYLD_LIBRARY_PATH was set *before this process was
exec'd* (macOS's dyld reads DYLD_* once at process launch and does not
re-consult them if mutated later, e.g. via os.environ in already-running
code) -- so relying on the app's launch environment already having it set
is fragile (confirmed: the running Flask process's own environment does not
have it, even though the user's login shell's .zprofile does). Instead we
find and load the library by full path ourselves and monkeypatch `hid`'s
loader to hand back that already-loaded handle -- see _import_hid().
"""

from __future__ import annotations

import ctypes
import dataclasses
import glob
import json
import logging
import os
import threading
import time
from typing import Optional

import radio_control

log = logging.getLogger("rigdial_bridge")

VENDOR_NAME = "Contour Design"
PRODUCT_NAME = "ShuttleXpress"

BUTTON_COUNT = 5

BUTTON_ACTIONS = (
    "none", "ptt", "step_toggle", "band_up", "band_down",
    "mod_power", "mod_rit", "mod_xit", "mod_micgain",
)
SHUTTLE_ACTIONS = ("none", "cycle_presets")

_MOD_BUTTON_ACTIONS = {"mod_power", "mod_rit", "mod_xit", "mod_micgain"}

# Candidate install locations for the native hidapi library, covering
# MacPorts (what this machine has), Homebrew (Apple Silicon and Intel), and
# a couple of common Linux paths -- extend if a future install location
# doesn't match.
_NATIVE_LIB_CANDIDATES = [
    "/opt/local/lib/libhidapi.dylib",
    "/opt/homebrew/lib/libhidapi.dylib",
    "/usr/local/lib/libhidapi.dylib",
    "/usr/lib/x86_64-linux-gnu/libhidapi-hidraw.so",
    "/usr/lib/x86_64-linux-gnu/libhidapi-libusb.so",
]


def _find_native_lib() -> Optional[str]:
    for path in _NATIVE_LIB_CANDIDATES:
        if os.path.exists(path):
            return path
    for pattern in ("/opt/local/lib/libhidapi*.dylib", "/opt/homebrew/lib/libhidapi*.dylib"):
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
    return None


def _import_hid():
    """Import the `hid` package, pre-loading the native library by full path
    if we can find one it wouldn't otherwise discover (see module
    docstring). Returns the module, or None if `hid` isn't installed at all
    (pip install hid) or no native library could be loaded either way --
    callers must treat that as "no hardware support available", not a fatal
    error, since the rest of the app (frequency presets, etc.) works fine
    without it."""
    native_path = _find_native_lib()
    if native_path:
        try:
            handle = ctypes.CDLL(native_path)
            _orig_load_library = ctypes.cdll.LoadLibrary

            def _patched_load_library(name, _orig=_orig_load_library, _handle=handle):
                if "hidapi" in name:
                    return _handle
                return _orig(name)

            ctypes.cdll.LoadLibrary = _patched_load_library
        except OSError:
            log.exception("Found %s but couldn't load it", native_path)
    try:
        import hid
        return hid
    except ImportError as exc:
        log.warning(
            "hid package or native hidapi library not available (%s) -- "
            "RigDial hardware control disabled, presets/config still work", exc,
        )
        return None


_hid = _import_hid()


# ---------------------------------------------------------------------------
# Config (button/jog/shuttle mapping) -- JSON-backed, same pattern as
# radio_control.RigctldProcessConfig.
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class RigDialConfig:
    # Keys are button indices as strings ("0".."4") since JSON object keys
    # are always strings anyway. Defaults match the original script's
    # hardcoded behavior: button 0 = PTT, button 2 = step toggle, button 3 =
    # mic gain modifier, button 4 = power modifier.
    button_actions: dict = dataclasses.field(default_factory=lambda: {
        "0": "ptt", "1": "none", "2": "step_toggle", "3": "mod_micgain", "4": "mod_power",
    })
    shuttle_action: str = "cycle_presets"
    jog_step_small_hz: float = 10
    jog_step_big_hz: float = 1000

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RigDialConfig":
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in known})


class RigDialConfigStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()

    def load(self) -> RigDialConfig:
        with self._lock:
            if not os.path.exists(self.path):
                return RigDialConfig()
            try:
                with open(self.path, "r") as f:
                    return RigDialConfig.from_dict(json.load(f))
            except (OSError, json.JSONDecodeError):
                log.exception("Could not read %s", self.path)
                return RigDialConfig()

    def save(self, cfg: RigDialConfig):
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(cfg.to_dict(), f, indent=2)
            os.replace(tmp, self.path)


# ---------------------------------------------------------------------------
# Frequency presets -- JSON-backed list, same id/lock pattern as
# qso_queue.QsoQueue. Seeded on first run from the original rigdial.py's
# hardcoded Freq.freq dict (2026-07-16 source) -- names kept as the
# original's dict keys verbatim (e.g. "B160MC") rather than guessed-at
# friendly labels, since only the user knows what the "C"/"C2"/"C3" suffixes
# meant to them; rename freely via the GUI.
# ---------------------------------------------------------------------------

_SEED_PRESETS = [
    ("B160M", 1_840_000), ("B160MC", 1_836_000),
    ("B80M", 3_573_000), ("B80MC2", 3_570_000),
    ("B40M", 7_074_000), ("B40MC2", 7_056_000),
    ("B30M", 10_136_000), ("B30MC3", 10_140_000),
    ("B20M", 14_074_000), ("B20MC2", 14_098_000),
    ("B17M", 18_100_000), ("B17MC", 18_095_000), ("B17MC2", 18_090_000),
    ("B15M", 21_074_000), ("B15MC2", 21_085_000),
    ("B12M", 24_915_000), ("B12MC2", 24_918_000),
    ("B10M", 28_074_000), ("B10MC", 28_090_000), ("B10MC2", 28_085_000),
    ("B6M", 50_313_000), ("B6MC", 50_331_000),
]


class RigDialPresetStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()

    def _load_locked(self) -> list:
        if not os.path.exists(self.path):
            presets = [
                {"id": i + 1, "name": name, "freq_hz": freq}
                for i, (name, freq) in enumerate(_SEED_PRESETS)
            ]
            self._save(presets)
            return presets
        try:
            with open(self.path, "r") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            log.exception("Could not read %s", self.path)
            return []

    def load(self) -> list:
        with self._lock:
            return self._load_locked()

    def _save(self, presets: list):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(presets, f, indent=2)
        os.replace(tmp, self.path)

    def add(self, name: str, freq_hz: float) -> dict:
        with self._lock:
            presets = self._load_locked()
            next_id = (max((p["id"] for p in presets), default=0)) + 1
            preset = {"id": next_id, "name": name, "freq_hz": freq_hz}
            presets.append(preset)
            self._save(presets)
            return preset

    def update(self, preset_id: int, name: Optional[str] = None, freq_hz: Optional[float] = None) -> Optional[dict]:
        with self._lock:
            presets = self._load_locked()
            for p in presets:
                if p["id"] == preset_id:
                    if name is not None:
                        p["name"] = name
                    if freq_hz is not None:
                        p["freq_hz"] = freq_hz
                    self._save(presets)
                    return p
            return None

    def delete(self, preset_id: int):
        with self._lock:
            presets = [p for p in self._load_locked() if p["id"] != preset_id]
            self._save(presets)


# ---------------------------------------------------------------------------
# Device reading + action dispatch
# ---------------------------------------------------------------------------

class RigDial:
    def __init__(self, config_store: RigDialConfigStore, preset_store: RigDialPresetStore):
        self.config_store = config_store
        self.preset_store = preset_store

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._status_lock = threading.Lock()
        self.connected = False
        self.last_event = ""
        self.last_event_at: Optional[float] = None

        self._held_buttons: set = set()
        self._preset_index = 0
        self._use_big_step = False
        self._max_shuttle = 0

    # -- status, for the Flask status poll --
    def status(self) -> dict:
        with self._status_lock:
            return {
                "hid_available": _hid is not None,
                "connected": self.connected,
                "last_event": self.last_event,
                "last_event_at": self.last_event_at,
                "current_step_hz": self._current_step_hz(),
            }

    def _set_status(self, *, connected: Optional[bool] = None, event: Optional[str] = None):
        with self._status_lock:
            if connected is not None:
                self.connected = connected
            if event is not None:
                self.last_event = event
                self.last_event_at = time.time()

    def _current_step_hz(self) -> float:
        cfg = self.config_store.load()
        return cfg.jog_step_big_hz if self._use_big_step else cfg.jog_step_small_hz

    # -- lifecycle --
    def start(self):
        if _hid is None:
            log.warning("Not starting RigDial reader thread -- hid package/native library unavailable")
            return
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._supervisor_loop, name="rigdial-hid", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    # -- device supervisor: (re)connect loop, tolerates unplug/replug --
    def _supervisor_loop(self):
        while not self._stop.is_set():
            target = self._find_device()
            if target is None:
                self._set_status(connected=False)
                self._stop.wait(2.0)
                continue
            try:
                dev = _hid.Device(path=target["path"])
            except Exception:
                log.exception("Failed to open ShuttleXpress")
                self._set_status(connected=False)
                self._stop.wait(2.0)
                continue
            log.info("RigDial: ShuttleXpress connected")
            self._set_status(connected=True, event="Device connected")
            try:
                self._read_loop(dev)
            except Exception:
                log.exception("RigDial read loop error -- will retry")
            finally:
                try:
                    dev.close()
                except Exception:
                    pass
            self._set_status(connected=False, event="Device disconnected")

    def _find_device(self) -> Optional[dict]:
        try:
            for d in _hid.enumerate():
                if d.get("manufacturer_string") == VENDOR_NAME and d.get("product_string") == PRODUCT_NAME:
                    return d
        except Exception:
            log.exception("hid.enumerate() failed")
        return None

    def _read_loop(self, dev):
        jog_value = None
        shuttle_value = 0
        jog_time = None
        buttons = [False] * BUTTON_COUNT

        while not self._stop.is_set():
            data = dev.read(8, timeout=500)
            if not data:
                continue  # idle -- device only reports on state change
            if len(data) < 5:
                continue
            b0, b1, b3, b4 = data[0], data[1], data[3], data[4]

            new_shuttle = b0 & 0x0F
            if new_shuttle > 8:
                new_shuttle = -(16 - new_shuttle)
            if new_shuttle != shuttle_value:
                shuttle_value = new_shuttle
                self._on_shuttle(shuttle_value)

            new_buttons = [
                bool(b3 & 0x10), bool(b3 & 0x20), bool(b3 & 0x40), bool(b3 & 0x80), bool(b4 & 0x01),
            ]
            for i in range(BUTTON_COUNT):
                if new_buttons[i] != buttons[i]:
                    buttons[i] = new_buttons[i]
                    self._on_button(i, buttons[i])

            if jog_value is None:
                jog_value = b1
            if jog_value != b1:
                delta = b1 - jog_value
                if delta < -128:
                    delta += 256
                if delta > 120:
                    delta -= 256
                jog_value = b1
                now = time.time() * 1000
                delta_time = now - jog_time if jog_time is not None else 1.0
                jog_time = now
                velocity = (delta / max(delta_time, 1.0)) * 1000 * 3.5
                self._on_jog(delta, velocity)

    # -- event handlers --
    def _on_button(self, index: int, pressed: bool):
        if pressed:
            self._held_buttons.add(index)
        else:
            self._held_buttons.discard(index)
        cfg = self.config_store.load()
        action = cfg.button_actions.get(str(index), "none")
        self._set_status(event=f"Button {index + 1} {'pressed' if pressed else 'released'} ({action})")

        if action in _MOD_BUTTON_ACTIONS:
            return  # handled as a jog modifier only, see _on_jog

        if action == "ptt":
            # Needs both edges (key on press, un-key on release) -- must not
            # be gated by the press-only check below, or a release would
            # never reach set_ptt(False) and the rig would stay keyed.
            client = radio_control.get_client()
            if client is not None:
                try:
                    client.set_ptt(pressed)
                except (radio_control.RigctldError, radio_control.RigctldConnectionError) as exc:
                    log.warning("RigDial PTT failed: %s", exc)
            return

        if not pressed:
            return  # remaining actions fire on the press edge only

        try:
            if action == "step_toggle":
                self._use_big_step = not self._use_big_step
            elif action == "band_up":
                self._cycle_preset(1)
            elif action == "band_down":
                self._cycle_preset(-1)
        except (radio_control.RigctldError, radio_control.RigctldConnectionError) as exc:
            log.warning("RigDial button %d (%s) failed: %s", index, action, exc)

    def _on_shuttle(self, value: int):
        if abs(value) > 1 and abs(value) > abs(self._max_shuttle):
            self._max_shuttle = value
        if value == 0 and self._max_shuttle != 0:
            direction = 1 if self._max_shuttle > 0 else -1
            self._max_shuttle = 0
            cfg = self.config_store.load()
            self._set_status(event=f"Shuttle return-to-zero ({cfg.shuttle_action})")
            if cfg.shuttle_action == "cycle_presets":
                self._cycle_preset(direction)

    def _on_jog(self, delta: int, velocity: float):
        cfg = self.config_store.load()
        held_mod = next(
            (cfg.button_actions.get(str(i)) for i in sorted(self._held_buttons)
             if cfg.button_actions.get(str(i)) in _MOD_BUTTON_ACTIONS),
            None,
        )
        client = radio_control.get_client()
        if client is None:
            return
        try:
            if held_mod == "mod_power":
                self._adjust_fraction(client.get_rfpower, client.set_rfpower, delta)
            elif held_mod == "mod_micgain":
                self._adjust_fraction(client.get_miclevel, client.set_miclevel, delta)
            elif held_mod == "mod_rit":
                client.set_rit(int(client.get_rit() + delta * 10))
            elif held_mod == "mod_xit":
                client.set_xit(int(client.get_xit() + delta * 10))
            else:
                mult = 1.0
                av = abs(velocity)
                if av < 30:
                    mult = 1.0
                elif av < 60:
                    mult = 4.0
                elif av < 90:
                    mult = 9.0
                else:
                    mult = 15.0
                step = self._current_step_hz()
                client.set_freq(client.get_freq() + step * delta * mult)
        except (radio_control.RigctldError, radio_control.RigctldConnectionError) as exc:
            log.warning("RigDial jog action (%s) failed: %s", held_mod or "vfo", exc)

    @staticmethod
    def _adjust_fraction(getter, setter, delta: int):
        current = getter()
        setter(max(0.0, min(1.0, current + delta * 0.01)))

    def _cycle_preset(self, direction: int):
        presets = self.preset_store.load()
        if not presets:
            return
        self._preset_index = (self._preset_index + direction) % len(presets)
        preset = presets[self._preset_index]
        client = radio_control.get_client()
        if client is None:
            return
        try:
            client.set_freq(preset["freq_hz"])
            self._set_status(event=f"Tuned to preset '{preset['name']}' ({preset['freq_hz']/1e6:.6f} MHz)")
        except (radio_control.RigctldError, radio_control.RigctldConnectionError) as exc:
            log.warning("RigDial preset cycle failed: %s", exc)


_dial: Optional[RigDial] = None


def init_rigdial_bridge(config_path: str = "rigdial_config.json", presets_path: str = "rigdial_presets.json") -> RigDial:
    global _dial
    _dial = RigDial(RigDialConfigStore(config_path), RigDialPresetStore(presets_path))
    _dial.start()
    return _dial


def get_dial() -> Optional[RigDial]:
    return _dial

import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import audio_spectrum


class _FastFakeStream:
    def __init__(self):
        self.aborted = False
        self.closed = False

    def abort(self, ignore_errors=True):
        self.aborted = True

    def close(self, ignore_errors=True):
        self.closed = True


class _FakeSpectrum:
    def __init__(self, stream):
        self.stream = stream


def test_atexit_close_stream_no_stream_is_a_noop():
    audio_spectrum._spectrum = None
    audio_spectrum._atexit_close_stream()  # must not raise


def test_atexit_close_stream_succeeds_quickly_when_stream_cooperates():
    stream = _FastFakeStream()
    audio_spectrum._spectrum = _FakeSpectrum(stream)
    try:
        t0 = time.monotonic()
        audio_spectrum._atexit_close_stream()
        elapsed = time.monotonic() - t0
        assert elapsed < 1.0, f"took {elapsed:.2f}s, expected a fast return"
        assert stream.aborted
        assert stream.closed
    finally:
        audio_spectrum._spectrum = None


def test_atexit_close_stream_force_exits_when_stream_hangs():
    # Regression (live 2026-08-15): sounddevice registers its own atexit
    # Pa_Terminate() hook, which hung forever inside a wedged CoreAudio HAL
    # mutex when the stream was left open across a reload -- the whole
    # process, and the reloader waiting on it, never recovered. Simulates
    # that exact hang (abort()/close() that never return) in a subprocess
    # -- os._exit() can't safely be exercised in-process -- and asserts
    # the process force-exits within the timeout instead of hanging.
    script = (
        "import sys, time\n"
        f"sys.path.insert(0, {os.path.join(os.path.dirname(__file__), '..')!r})\n"
        "import audio_spectrum\n"
        "class FakeStream:\n"
        "    def abort(self, ignore_errors=True):\n"
        "        time.sleep(999)\n"
        "    def close(self, ignore_errors=True):\n"
        "        time.sleep(999)\n"
        "class FakeSpectrum:\n"
        "    def __init__(self):\n"
        "        self.stream = FakeStream()\n"
        "audio_spectrum._spectrum = FakeSpectrum()\n"
        "audio_spectrum._atexit_close_stream()\n"
        "print('UNEXPECTED_RETURN')\n"
    )
    t0 = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=15,
    )
    elapsed = time.monotonic() - t0

    assert "UNEXPECTED_RETURN" not in proc.stdout, (
        "the hung close() should never return control -- os._exit() must fire first"
    )
    assert proc.returncode == 1, f"expected force-exit code 1, got {proc.returncode}"
    assert elapsed < audio_spectrum._ATEXIT_CLOSE_TIMEOUT_S + 5, (
        f"took {elapsed:.1f}s -- should force-exit around the {audio_spectrum._ATEXIT_CLOSE_TIMEOUT_S}s timeout"
    )

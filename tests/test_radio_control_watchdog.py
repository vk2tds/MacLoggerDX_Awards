import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import radio_control as rc


def _make_fake_rigctld(tmpdir):
    """A stand-in for the real rigctld binary: just sleeps, ignoring
    whatever CLI flags start() passes it. Good enough to test process
    lifecycle/watchdog behaviour without a real rig or Hamlib install.

    Must be a real compiled binary named "rigctld" (not a shebang script
    exec'd via /bin/sh) -- _tracked_pid()'s liveness check requires
    `ps -o comm=` to contain "rigctld" to guard against a recycled PID
    belonging to something else entirely, and a directly-exec'd shell
    script reports `comm` as the shell interpreter (e.g. "/bin/sh"), not
    the script's own name."""
    src = os.path.join(tmpdir, "rigctld.c")
    path = os.path.join(tmpdir, "rigctld")
    with open(src, "w") as f:
        f.write("#include <unistd.h>\nint main(void) { sleep(60); return 0; }\n")
    subprocess.run(["cc", "-o", path, src], check=True)
    return path


def _manager(tmpdir, binary):
    mgr = rc.RigctldProcessManager(
        os.path.join(tmpdir, "config.json"),
        os.path.join(tmpdir, "state.json"),
        os.path.join(tmpdir, "rigctld.log"),
    )
    mgr.save_config(rc.RigctldProcessConfig(
        rig_model=1, device="/dev/null", listen_host="127.0.0.1", listen_port=0, binary_path=binary,
    ))
    return mgr


def _wait_until_not_tracked(mgr, timeout_s=3.0):
    """Poll the manager's own liveness check (not a raw os.kill(pid, 0)) --
    a killed child is a zombie until reaped, so kill(pid, 0) alone keeps
    reporting it as alive. _tracked_pid()'s `ps -o comm=` check correctly
    reads "<defunct>" for a zombie and treats it as dead; that's the
    behaviour that actually matters here, not raw process-table state."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if mgr._tracked_pid() is None:
            return True
        time.sleep(0.05)
    return False


def test_start_sets_watchdog_enabled_and_stop_clears_it():
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = _manager(tmpdir, _make_fake_rigctld(tmpdir))
        ok, message = mgr.start()
        assert ok, message
        try:
            status = mgr.status()
            assert status["managed_running"] is True
            assert status["watchdog_enabled"] is True
        finally:
            mgr.stop()

        status = mgr.status()
        assert status["managed_running"] is False
        assert status["watchdog_enabled"] is False


def test_watchdog_tick_restarts_after_crash_but_not_after_explicit_stop():
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = _manager(tmpdir, _make_fake_rigctld(tmpdir))
        ok, message = mgr.start()
        assert ok, message
        first_pid = mgr.status()["managed_pid"]

        # Simulate the process dying out from under us (crash, killed by a
        # network/USB disruption, etc.) rather than being stopped via stop().
        os.kill(first_pid, 9)
        assert _wait_until_not_tracked(mgr), "manager never noticed the crash"

        mgr._watchdog_tick()
        status = mgr.status()
        try:
            assert status["managed_running"] is True
            assert status["managed_pid"] != first_pid
        finally:
            mgr.stop()

        # After an explicit stop(), a tick must NOT bring it back.
        mgr._watchdog_tick()
        status = mgr.status()
        assert status["managed_running"] is False


def test_status_reports_whether_configured_device_exists():
    """rigctld itself gives no sign when its USB-serial device vanishes --
    it keeps running and listening fine, every real command just times out
    with no explanation. status()'s device_exists field is what lets the UI
    show that instantly instead. Confirmed live 2026-09-22/23: this exact
    scenario (device unplugged/renumbered) happened twice in two days with
    no warning anywhere in the app."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = _manager(tmpdir, "/usr/bin/true")  # never started -- device_exists doesn't need a running process
        assert mgr.status()["device_exists"] is True  # _manager() configures device="/dev/null"

        cfg = mgr.load_config()
        cfg.device = os.path.join(tmpdir, "does-not-exist")
        mgr.save_config(cfg)
        assert mgr.status()["device_exists"] is False

        cfg.device = ""
        mgr.save_config(cfg)
        assert mgr.status()["device_exists"] is None


def test_clear_dead_pid_preserves_watchdog_enabled_flag():
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = _manager(tmpdir, _make_fake_rigctld(tmpdir))
        mgr._save_state({
            "pid": 999999999,  # never a real PID
            "started_at": time.time(),
            "command": ["fake"],
            "watchdog_enabled": True,
        })
        assert mgr._tracked_pid() is None

        state = mgr._load_state()
        assert state.get("watchdog_enabled") is True
        assert "pid" not in state
        assert "started_at" not in state


def test_tracked_pid_survives_a_failing_ps_call():
    """A failed/timed-out `ps` says nothing about the process; the state
    file must keep a PID that os.kill(pid, 0) proved alive. Confirmed live
    2026-10-09: treating it as "not rigctld" lost a healthy rigctld."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = _manager(tmpdir, "/usr/bin/true")
        mgr._save_state({"pid": os.getpid(), "watchdog_enabled": True})
        real_run = rc.subprocess.run

        def boom(*a, **kw):
            raise rc.subprocess.TimeoutExpired(cmd="ps", timeout=2)

        rc.subprocess.run = boom
        try:
            assert mgr._tracked_pid() == os.getpid()
        finally:
            rc.subprocess.run = real_run


def test_set_freq_turns_split_off_unless_allowed():
    """TX must follow VFO A after an app-initiated retune. Confirmed live
    2026-10-15: WSJT-X's "Rig" split left VFO B on 50 MHz while we tuned
    VFO A to 21 MHz, so the rig transmitted on 50 MHz."""
    sent = []

    class FakeClient(rc.RigctldClient):
        def __init__(self):
            self.split = True
            self.ptt = False

        def _command(self, cmd, expect_lines=0):
            sent.append(cmd)
            if cmd.startswith("\\get_split_vfo"):
                return ["1" if self.split else "0", "VFOB"]
            if cmd.startswith("\\get_ptt"):
                return ["1" if self.ptt else "0"]
            if cmd.startswith("\\set_split_vfo 0"):
                self.split = False
            return []

    with tempfile.TemporaryDirectory() as tmpdir:
        old_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            c = FakeClient()
            c.set_freq(21074000)
            assert c.split is False
            assert "\\set_split_vfo 0 VFOA" in sent

            # explicitly allowed -> left alone
            rc._set_split_allowed(True)
            c.split = True
            c.set_freq(14074000)
            assert c.split is True

            # never touched while keyed
            rc._set_split_allowed(False)
            c.ptt = True
            assert c.ensure_split_off() is False
            assert c.split is True
        finally:
            os.chdir(old_cwd)

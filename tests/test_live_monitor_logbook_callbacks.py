import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import live_monitor as lm


class _StubStatusChecker:
    def refresh_worked_sets(self):
        pass


def _bare_monitor(database_path):
    mon = lm.LiveMonitor.__new__(lm.LiveMonitor)
    mon.dxcc_resolver = None
    mon.status_checker = _StubStatusChecker()
    mon.config = lm.LiveMonitorConfig(
        database_path=database_path, qso_table="", dxcc_file="", my_call="VK2TDS",
        udp_host="127.0.0.1", udp_port=0, multicast_group=None,
    )
    mon.dx_history = []
    mon._logbook_change_callbacks = []
    return mon


def test_logbook_change_callback_fires_when_database_mtime_changes():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "fake.sql")
        with open(db_path, "w") as f:
            f.write("x")

        mon = _bare_monitor(db_path)
        mon._logbook_mtime_seen = mon._logbook_mtime()

        calls = []
        mon.add_logbook_change_callback(lambda: calls.append(1))

        # No change yet -- tick must be a no-op.
        mon._logbook_watchdog_tick()
        assert calls == []

        # Touch the file (mtime granularity can be coarse -- back-date the
        # "seen" mtime instead of racing the real clock).
        mon._logbook_mtime_seen -= 5
        mon._logbook_watchdog_tick()
        assert calls == [1]


def test_logbook_change_callback_failure_does_not_block_others_or_dx_status_refresh():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "fake.sql")
        with open(db_path, "w") as f:
            f.write("x")

        mon = _bare_monitor(db_path)
        mon._logbook_mtime_seen = mon._logbook_mtime() - 5

        calls = []

        def _boom():
            raise RuntimeError("simulated failure")

        mon.add_logbook_change_callback(_boom)
        mon.add_logbook_change_callback(lambda: calls.append("second"))

        refresh_calls = []
        mon._refresh_dx_history_status = lambda: refresh_calls.append(1)

        mon._logbook_watchdog_tick()
        assert refresh_calls == [1]
        assert calls == ["second"]

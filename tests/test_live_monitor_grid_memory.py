import os
import sys
import threading
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import live_monitor as lm
from dxcc_lookup import DxccResolver
from wsjtx_udp import WsjtxMessage

FIXTURE_DXCC = os.path.join(os.path.dirname(__file__), "fixture_dxcc.txt")


class _StubStatusChecker:
    """Minimal stand-in: _compute_status() fully tolerates db_status=None
    (every downstream field is guarded with `if db_status else None`), so a
    lookup() that always returns None is enough to isolate DXCC-entity
    resolution from the real database."""

    def lookup(self, *a, **kw):
        return None

    def refresh_worked_sets(self):
        pass

    def is_new_dxcc(self, dxcc_id):
        return False

    def entity_status_all_scopes(self, dxcc_id, band, mode):
        return {"overall": "none", "band": "none", "mode": "none", "band_mode": "none"}

    def grid_status_all_scopes(self, grid, band, mode):
        return {"overall": "none", "band": "none", "mode": "none", "band_mode": "none"}

    def is_new_grid4(self, grid):
        return False


def _bare_monitor():
    mon = lm.LiveMonitor.__new__(lm.LiveMonitor)
    mon.dxcc_resolver = DxccResolver(FIXTURE_DXCC)
    mon.status_checker = _StubStatusChecker()
    mon.wsjtx_status = {"dial_frequency_hz": 21074000}  # 15M
    mon.cq_filter_enabled = False
    mon.config = lm.LiveMonitorConfig(
        database_path="", qso_table="", dxcc_file=FIXTURE_DXCC, my_call="VK2TDS",
        udp_host="127.0.0.1", udp_port=0, multicast_group=None,
    )
    mon.history = deque()
    mon.dx_history = deque()
    mon._recent_decodes = deque()
    mon._recent_decodes_set = set()
    mon._last_grid_by_call = {}
    mon._last_cache_refresh = 0.0
    mon._clients_lock = threading.Lock()
    mon._clients = []
    return mon


def _decode(mon, message, time_ms=0):
    msg = WsjtxMessage(
        type=2, type_name="Decode", id="WSJT-X",
        fields={"time_ms": time_ms, "message": message, "mode": "FT8"},
        raw_len=0, source=("127.0.0.1", 2237),
    )
    mon._handle_decode(msg)


def test_grid_less_followup_keeps_earlier_grid_based_entity():
    """VK0DS CQs with a grid (resolves to Antarctica, ~68.5S 78E, Davis
    Station) and then exchanges a grid-less signal report on the same
    band -- the second decode must not fall back to VK0's ambiguous
    no-grid default (Heard I.) and overwrite the correct resolution.
    Regression: live 2026-09-01, VK0DS on 15M reverting to "Heard I."
    mid-QSO."""
    mon = _bare_monitor()
    _decode(mon, "CQ VK0DS MC81", time_ms=1000)
    assert mon.dx_history[-1]["dxcc_name"] == "Antarctica"

    _decode(mon, "VK2TDS VK0DS -12", time_ms=2000)
    assert mon.dx_history[-1]["dxcc_name"] == "Antarctica"
    assert mon.dx_history[-1]["grid"] is None


def test_grid_less_decode_with_no_prior_grid_keeps_heard_default():
    mon = _bare_monitor()
    _decode(mon, "VK2TDS VK0DS -12", time_ms=1000)
    assert mon.dx_history[-1]["dxcc_name"] == "Heard I."


def test_refresh_dx_history_status_uses_remembered_grid_not_latest_events_own():
    mon = _bare_monitor()
    _decode(mon, "CQ VK0DS MC81", time_ms=1000)
    _decode(mon, "VK2TDS VK0DS -12", time_ms=2000)
    assert mon.dx_history[-1]["dxcc_name"] == "Antarctica"

    mon._refresh_dx_history_status()
    assert mon.dx_history[-1]["dxcc_name"] == "Antarctica"

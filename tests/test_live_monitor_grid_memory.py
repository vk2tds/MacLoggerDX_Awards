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


def test_compound_callsign_dxcc_uses_operating_location_not_home_entity():
    """A JA1ABC operator signing "W6/JA1ABC" is operating from the USA right
    now -- DXCC must resolve to United States of America, not Japan.
    ft8_parser.base_callsign() strips this down to "JA1ABC" (the longer,
    more callsign-shaped side) for operator-identity matching, which is
    correct for "have I worked this operator before" but wrong for DXCC:
    feeding that stripped form into the resolver silently resolves to the
    operator's home country instead of where they're actually transmitting
    from. Regression: live 2026-09-17, W6/UT5UF was grouped under "Ukraine"
    on DX Monitor instead of USA."""
    mon = _bare_monitor()
    _decode(mon, "CQ W6/JA1ABC CM87", time_ms=1000)
    assert mon.dx_history[-1]["dxcc_name"] == "United States of America"


def test_refresh_dx_history_status_uses_remembered_grid_not_latest_events_own():
    mon = _bare_monitor()
    _decode(mon, "CQ VK0DS MC81", time_ms=1000)
    _decode(mon, "VK2TDS VK0DS -12", time_ms=2000)
    assert mon.dx_history[-1]["dxcc_name"] == "Antarctica"

    mon._refresh_dx_history_status()
    assert mon.dx_history[-1]["dxcc_name"] == "Antarctica"


def test_worked_callsign_uses_logbook_entity_over_ambiguous_prefix():
    """Bare "FO" belongs to several DXCC entities, so the prefix resolver
    can't tell them apart; the logbook knows which one a worked callsign
    really is. Regression: live 2026-10-16, FO5QB (French Polynesia in the
    log) was grouped under "Austral I." in red while its own callsign
    colour was correctly purple."""
    class Row:
        dxcc_id = 291  # fixture: United States of America
        dxcc_country = "United States of America"
        cq_zone = None
        worked_before = True
        worked_this_band = True
        confirmed_ever = False
        confirmed_this_band = False
        error = None

        def status_all_scopes(self):
            return {"overall": "worked", "band": "worked", "mode": "worked", "band_mode": "worked"}

    mon = _bare_monitor()
    mon.status_checker.lookup = lambda *a, **kw: Row()
    # JA1ABC resolves to Japan by prefix; the logbook says it's the USA.
    _decode(mon, "CQ JA1ABC PM95", time_ms=1000)
    assert mon.dx_history[-1]["dxcc_name"] == "United States of America"

    # ...but a compound call keeps the operating-location prefix, not the logbook's home entity.
    _decode(mon, "CQ W6/JA1ABC CM87", time_ms=2000)
    assert mon.dx_history[-1]["dxcc_name"] == "United States of America"
    _decode(mon, "CQ JA2/JA1ABC PM95", time_ms=3000)
    assert mon.dx_history[-1]["dxcc_name"] == "Japan"


def test_compound_call_in_another_entity_ignores_base_callsign_logbook_rows():
    """VK9/VK2DAG operates from Cocos (Keeling), not Australia, so the
    operator's home VK2DAG QSOs must not make this callsign look worked.
    Regression: live 2026-10-16, VK9/VK2DAG purple under a red "Christmas
    I." box. A plain /P suffix stays in the same entity and keeps the
    base-call fallback."""
    seen = []
    mon = _bare_monitor()
    mon.status_checker.lookup = lambda call, base_callsign=None, **kw: seen.append((call, base_callsign)) or None
    _decode(mon, "CQ VK9/VK2DAG QG22", time_ms=1000)
    _decode(mon, "CQ VK2DAG/P QF56", time_ms=2000)
    assert seen[0] == ("VK9/VK2DAG", None)
    assert seen[1] == ("VK2DAG/P", "VK2DAG")

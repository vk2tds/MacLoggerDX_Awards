import os
import sys
import threading
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import live_monitor as lm


def _bare_monitor(wsjtx_status=None):
    """A LiveMonitor with just enough state for the reply-dispatch methods,
    skipping __init__'s DB/DXCC-file setup."""
    mon = lm.LiveMonitor.__new__(lm.LiveMonitor)
    mon.wsjtx_status = wsjtx_status or {}
    mon._last_wsjtx_id = "WSJT-X"
    mon._last_wsjtx_addr = ("127.0.0.1", 2237)
    mon._transport = None
    mon._loop = None
    mon.history = deque()
    mon._recent_decodes = deque()
    mon._recent_decodes_set = set()
    mon._clients_lock = threading.Lock()
    mon._clients = []
    return mon


def test_reply_action_uses_reply_for_cq():
    mon = _bare_monitor()
    calls = []
    mon.send_reply = lambda ev: calls.append(("reply", ev))
    mon.send_call_via_configure = lambda ev: calls.append(("configure", ev))

    ev = {"is_cq": True, "call": "VK2ABC"}
    mon.handle_reply_action(ev)
    assert calls == [("reply", ev)]


def test_reply_action_uses_configure_for_non_cq():
    mon = _bare_monitor()
    calls = []
    mon.send_reply = lambda ev: calls.append(("reply", ev))
    mon.send_call_via_configure = lambda ev: calls.append(("configure", ev))

    ev = {"is_cq": False, "call": "VK2ABC"}
    mon.handle_reply_action(ev)
    assert calls == [("configure", ev)]


def test_configure_call_no_call_returns_false():
    mon = _bare_monitor()
    assert mon.send_call_via_configure({}) is False


def test_configure_call_uses_sane_status_tr_period():
    mon = _bare_monitor(wsjtx_status={"tr_period": 6, "frequency_tolerance": 20, "mode": "FT4"})
    captured = {}
    mon.send_configure = lambda **kw: captured.update(kw) or True

    ok = mon.send_call_via_configure({"call": "VK2ABC", "mode": "FT4", "grid": "QF56", "delta_freq_hz": 1200})
    assert ok is True
    assert captured["tr_period"] == 6
    assert captured["frequency_tolerance"] == 20
    assert captured["dx_call"] == "VK2ABC"
    assert captured["dx_grid"] == "QF56"
    assert captured["rx_df"] == 1200


def test_configure_call_falls_back_when_status_has_sentinel():
    # WSJT-X reports the quint32 "not available" sentinel for these fields
    # sometimes -- must not be passed through as a literal T/R period.
    mon = _bare_monitor(wsjtx_status={"tr_period": 4294967295, "frequency_tolerance": 4294967295, "mode": "FT8"})
    captured = {}
    mon.send_configure = lambda **kw: captured.update(kw) or True

    mon.send_call_via_configure({"call": "VK2ABC", "mode": "FT8"})
    assert captured["tr_period"] == 15  # per-mode default for FT8
    assert captured["frequency_tolerance"] == 10  # generic fallback

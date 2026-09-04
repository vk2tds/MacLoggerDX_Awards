import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from qsl_helper import _other_call_for, _auto_close_confirmed_methods, QslMethods

MY_BASES = {"VK2TDS", "AX2TDS"}


def test_other_call_plain_exchange():
    assert _other_call_for("W1AW VK2TDS -14", MY_BASES) == "W1AW"
    assert _other_call_for("VK2TDS W1AW R-09", MY_BASES) == "W1AW"


def test_other_call_hashed_but_resolved_strips_brackets():
    # Regression: WSJT-X's "<...>" hashed-callsign slot can carry a real,
    # decoded callsign (not the literal unresolved "<...>" placeholder) --
    # indexing it with the brackets still attached meant these QSOs could
    # never be found again by their plain callsign (St. Kitts V4/SP9FIH,
    # Taiwan BV400 both went missing this way).
    # base_callsign() reduces "V4/SP9FIH" to its home call "SP9FIH" -- that's
    # fine as long as it's applied consistently on both the index-build side
    # (here) and the query side (find_exchange(), which reduces the qso_table
    # call the same way), which it is.
    assert _other_call_for("<V4/SP9FIH> VK2TDS QF55", MY_BASES) == "SP9FIH"
    assert _other_call_for("VK2TDS <V4/SP9FIH> -12", MY_BASES) == "SP9FIH"
    assert _other_call_for("<BV400> VK2TDS QF55", MY_BASES) == "BV400"
    assert _other_call_for("VK2TDS <BV400> -21", MY_BASES) == "BV400"


def test_other_call_unresolved_hash_returns_none():
    assert _other_call_for("CQ <...> QF56", MY_BASES) is None
    assert _other_call_for("VK2TDS <...> -12", MY_BASES) is None


def test_other_call_ignores_cq_and_third_party_exchanges():
    assert _other_call_for("CQ VK2ABC QF56", MY_BASES) is None
    assert _other_call_for("W1AW K1ABC -10", MY_BASES) is None


def _make_methods(entries):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    methods = QslMethods(path)
    for call, method, status in entries:
        methods.upsert(call, method, "", "")
        if status != "pending":
            methods.set_status(call, status)
    return methods, path


def test_auto_close_confirmed_methods_marks_confirmed_call_done(qso_table, db_path):
    # Regression/feature: a QSL To-Do entry only ever flipped to "done" via
    # a manual click -- a real confirmation landing (e.g. via LoTW sync)
    # left it stuck "pending" forever unless the operator remembered.
    methods, methods_path = _make_methods([("W1AW", "Direct", "pending")])
    try:
        entries = _auto_close_confirmed_methods(db_path, qso_table, methods)
        assert entries[0]["status"] == "done"
        # Persisted, not just returned -- a fresh load must agree.
        assert methods.load()[0]["status"] == "done"
    finally:
        os.unlink(methods_path)


def test_auto_close_confirmed_methods_leaves_unconfirmed_pending(qso_table, db_path):
    methods, methods_path = _make_methods([("K1ABC", "Bureau", "pending")])
    try:
        entries = _auto_close_confirmed_methods(db_path, qso_table, methods)
        assert entries[0]["status"] == "pending"
    finally:
        os.unlink(methods_path)


def test_auto_close_confirmed_methods_never_reopens_a_done_entry(qso_table, db_path):
    # K1ABC has no confirmed QSO in the fixture DB -- if this ever
    # auto-reopened a manually-closed entry, that would be a real
    # regression (reopening must stay a deliberate manual action).
    methods, methods_path = _make_methods([("K1ABC", "Bureau", "done")])
    try:
        entries = _auto_close_confirmed_methods(db_path, qso_table, methods)
        assert entries[0]["status"] == "done"
    finally:
        os.unlink(methods_path)

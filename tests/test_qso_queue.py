import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from qso_queue import QsoQueue

REC = dict(
    my_call="VK2TDS", my_grid="QF55KX", call="JA1ABC", grid="PM95",
    mode="FT8", band="20M", tx_frequency_mhz=14.074,
    rst_sent="-10", rst_received="-12",
    dxcc_country="Japan", dxcc_id=339, cq_zone="25",
)


def _queue():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)  # QsoQueue creates it lazily
    return QsoQueue(path), path


def test_add_assigns_incrementing_ids():
    q, path = _queue()
    try:
        e1 = q.add(REC)
        e2 = q.add(REC)
        assert e1["id"] == 1
        assert e2["id"] == 2
        assert len(q.load()) == 2
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_add_defaults_to_pending_status():
    q, path = _queue()
    try:
        e = q.add(REC)
        assert e["status"] == "pending"
        assert e["error"] is None
        assert e["call"] == "JA1ABC"
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_mark_sent_and_mark_error():
    q, path = _queue()
    try:
        e = q.add(REC)
        q.mark_sent(e["id"])
        assert q.get(e["id"])["status"] == "sent"

        e2 = q.add(REC)
        q.mark_error(e2["id"], "boom")
        got = q.get(e2["id"])
        assert got["status"] == "error"
        assert got["error"] == "boom"
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_pending_ids_excludes_sent_and_error():
    q, path = _queue()
    try:
        pending = q.add(REC)
        sent = q.add(REC)
        q.mark_sent(sent["id"])
        errored = q.add(REC)
        q.mark_error(errored["id"], "boom")

        assert q.pending_ids() == [pending["id"]]
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_clear_sent_removes_only_sent_entries():
    q, path = _queue()
    try:
        pending = q.add(REC)
        sent = q.add(REC)
        q.mark_sent(sent["id"])
        errored = q.add(REC)
        q.mark_error(errored["id"], "boom")

        remaining = q.clear_sent()
        remaining_ids = {e["id"] for e in remaining}
        assert remaining_ids == {pending["id"], errored["id"]}
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_delete_removes_entry():
    q, path = _queue()
    try:
        e = q.add(REC)
        remaining = q.delete(e["id"])
        assert remaining == []
        assert q.get(e["id"]) is None
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_reentrant_lock_does_not_deadlock():
    # Regression class: qsl_helper.QslMethods originally deadlocked because
    # a write method called a read method while holding a plain (non-
    # reentrant) Lock. Confirm QsoQueue doesn't repeat that mistake.
    q, path = _queue()
    try:
        e = q.add(REC)
        q.mark_sent(e["id"])
        q.delete(e["id"])
    finally:
        if os.path.exists(path):
            os.unlink(path)

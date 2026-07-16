import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import pytest
except ImportError:  # pragma: no cover - fallback for the no-pytest sandbox runner
    class _DummyPytest:
        @staticmethod
        def fixture(*a, **k):
            def deco(fn):
                return fn
            return deco
    pytest = _DummyPytest()

from log_writer import QsoRecord, find_possible_duplicate, insert_qso


@pytest.fixture()
def db_path():
    fd, path = tempfile.mkstemp(suffix=".sql")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE qso_table_v008 (
            pk INTEGER PRIMARY KEY,
            my_call TEXT, my_grid TEXT, call TEXT, grid TEXT,
            dxcc_country TEXT, dxcc_id INTEGER, cq_zone TEXT,
            mode TEXT, band_rx TEXT, band_tx TEXT,
            rst_sent TEXT, rst_received TEXT,
            qsl_sent TEXT, qsl_received TEXT, comments TEXT,
            qso_start REAL, qso_done REAL,
            tx_frequency REAL, rx_frequency REAL,
            distance REAL, azimuth REAL, latitude REAL, longitude REAL
        )
        """
    )
    conn.commit()
    conn.close()
    yield path
    os.unlink(path)


def _rec(**overrides):
    base = dict(
        my_call="VK2TDS", my_grid="QF55KX", call="JA1ABC", grid="PM95",
        mode="FT8", band="20M", tx_frequency_mhz=14.074,
        rst_sent="-10", rst_received="-12",
        dxcc_country="Japan", dxcc_id=339, cq_zone="25",
        qso_start=1700000000.0, qso_done=1700000060.0,
    )
    base.update(overrides)
    return QsoRecord(**base)


def test_insert_qso_writes_expected_row(db_path):
    pk = insert_qso(db_path, "qso_table_v008", _rec())
    assert pk is not None
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT my_call, call, grid, mode, band_tx, band_rx, rst_sent, rst_received, "
        "tx_frequency, rx_frequency, dxcc_country, dxcc_id, cq_zone, distance, azimuth "
        "FROM qso_table_v008 WHERE pk = ?", (pk,)
    ).fetchone()
    conn.close()
    assert row == ("VK2TDS", "JA1ABC", "PM95", "FT8", "20M", "20M", "-10", "-12",
                    14.074, 14.074, "Japan", 339, "25", None, None)


def test_insert_qso_leaves_distance_unset_matching_short_grid_convention(db_path):
    # Confirmed against the real log: rows with only a 4-char grid show
    # distance/azimuth as 0.0/computed-from-default rather than a real
    # value -- we deliberately don't fabricate one, so the column should
    # just be left at SQLite's default (NULL here), not populated.
    pk = insert_qso(db_path, "qso_table_v008", _rec())
    conn = sqlite3.connect(db_path)
    distance = conn.execute("SELECT distance FROM qso_table_v008 WHERE pk = ?", (pk,)).fetchone()[0]
    conn.close()
    assert distance is None


def test_find_possible_duplicate_detects_recent_same_call_band_mode(db_path):
    insert_qso(db_path, "qso_table_v008", _rec(qso_start=1700000000.0))
    dup = find_possible_duplicate(db_path, "qso_table_v008", "JA1ABC", "20M", "FT8", near_epoch=1700000500.0)
    assert dup is not None


def test_find_possible_duplicate_ignores_old_or_different_contact(db_path):
    insert_qso(db_path, "qso_table_v008", _rec(qso_start=1700000000.0))
    # Way outside the duplicate window
    far = find_possible_duplicate(db_path, "qso_table_v008", "JA1ABC", "20M", "FT8", near_epoch=1700100000.0)
    assert far is None
    # Different band
    other_band = find_possible_duplicate(db_path, "qso_table_v008", "JA1ABC", "40M", "FT8", near_epoch=1700000500.0)
    assert other_band is None
    # Different call
    other_call = find_possible_duplicate(db_path, "qso_table_v008", "JA9XYZ", "20M", "FT8", near_epoch=1700000500.0)
    assert other_call is None

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

from log_status import LogStatusChecker


@pytest.fixture()
def db_path():
    fd, path = tempfile.mkstemp(suffix=".sql")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE qso_table_v008 (
            call TEXT,
            dxcc_country TEXT,
            dxcc_id INTEGER,
            cq_zone TEXT,
            band_rx TEXT,
            mode TEXT,
            qsl_sent TEXT,
            qsl_received TEXT,
            grid TEXT
        )
        """
    )
    rows = [
        ("VK2ABC", "Australia", 150, "30", "20M", "FT8", "", "LoTW: 20230101", "QF56aa"),
        ("VK2ABC", "Australia", 150, "30", "40M", "FT8", "", "", "QF56aa"),
        ("W1AW", "United States of America", 291, "05", "20M", "FT8", "", "", "FN31pr"),
    ]
    conn.executemany(
        "INSERT INTO qso_table_v008 (call, dxcc_country, dxcc_id, cq_zone, band_rx, mode, qsl_sent, qsl_received, grid) VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    yield path
    os.unlink(path)


def test_schema_introspection(db_path):
    checker = LogStatusChecker(db_path, "qso_table_v008")
    assert checker.has_column("call")
    assert checker.has_column("dxcc_id")
    assert not checker.has_column("state")  # column that doesn't exist in this fixture


def test_lookup_never_worked(db_path):
    checker = LogStatusChecker(db_path, "qso_table_v008")
    status = checker.lookup("JA1ABC")
    assert status.worked_before is False
    assert status.qso_count == 0


def test_lookup_worked_before(db_path):
    checker = LogStatusChecker(db_path, "qso_table_v008")
    status = checker.lookup("VK2ABC", band="20M", mode="FT8")
    assert status.worked_before is True
    assert status.qso_count == 2
    assert status.worked_this_band is True
    assert status.confirmed_ever is True
    assert status.confirmed_this_band is True


def test_lookup_worked_different_band_not_confirmed(db_path):
    checker = LogStatusChecker(db_path, "qso_table_v008")
    status = checker.lookup("VK2ABC", band="80M", mode="FT8")
    assert status.worked_before is True
    assert status.worked_this_band is False
    assert status.confirmed_this_band is False
    assert status.confirmed_ever is True  # confirmed on a *different* band


def test_lookup_by_base_callsign_for_portable(db_path):
    checker = LogStatusChecker(db_path, "qso_table_v008")
    status = checker.lookup("VK2ABC/P", base_callsign="VK2ABC")
    assert status.worked_before is True


def test_worked_sets_and_new_dxcc_flag(db_path):
    checker = LogStatusChecker(db_path, "qso_table_v008")
    checker.refresh_worked_sets()
    assert checker.is_new_dxcc(150) is False   # VK already worked
    assert checker.is_new_dxcc(339) is True    # Japan never worked
    assert checker.is_new_cq_zone("30") is False
    assert checker.is_new_cq_zone("99") is True
    assert checker.is_new_grid4("QF56aa") is False
    assert checker.is_new_grid4("PM95aa") is True


def test_missing_database_reports_error_not_crash(tmp_path):
    checker = LogStatusChecker(str(tmp_path / "does_not_exist.sql"), "qso_table_v008")
    status = checker.lookup("VK2ABC")
    assert status.error is not None


@pytest.fixture()
def cardc_db_path():
    """Separate fixture (rather than adding rows to db_path) so this
    doesn't disturb the row-count/worked assertions the other tests make
    against that shared fixture."""
    fd, path = tempfile.mkstemp(suffix=".sql")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE qso_table_v008 (
            call TEXT, dxcc_country TEXT, dxcc_id INTEGER, cq_zone TEXT,
            band_rx TEXT, mode TEXT, qsl_sent TEXT, qsl_received TEXT, grid TEXT
        )
        """
    )
    rows = [
        # Physical card in hand, no LoTW -- should count as "confirmed" for
        # the live status coloring (confirmed_lotw_or_card_*) but NOT for
        # the strict LoTW-only fields (confirmed_lotw_*), since the
        # callsign-history modal needs to keep saying "eQSL/card", not
        # falsely claim LoTW.
        ("7X2ABC", "Algeria", 400, "33", "20M", "FT8", "", "CardC:20250304", "MM12aa"),
        # eQSL only -- CONFIRMED_LIKE/confirmed_ever counts this, but the
        # narrower CardC-or-LoTW check must not (user asked for "Just
        # CardC", not eQSL).
        ("7X3DEF", "Algeria", 400, "33", "40M", "FT8", "", "eQSL: 20240101", "MM12bb"),
    ]
    conn.executemany(
        "INSERT INTO qso_table_v008 (call, dxcc_country, dxcc_id, cq_zone, band_rx, mode, qsl_sent, qsl_received, grid) VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    yield path
    os.unlink(path)


def test_cardc_counts_as_confirmed_for_live_status_not_for_lotw_field(cardc_db_path):
    checker = LogStatusChecker(cardc_db_path, "qso_table_v008")
    status = checker.lookup("7X2ABC", band="20M", mode="FT8")
    assert status.confirmed_ever is True  # CONFIRMED_LIKE already covers CardC
    assert status.confirmed_lotw_ever is False  # not actually LoTW
    assert status.confirmed_lotw_or_card_ever is True  # but counts for live coloring
    assert status.confirmed_lotw_or_card_this_band is True
    assert status.status_for_scope(True, False) == "confirmed"  # Call cell colouring


def test_eqsl_alone_does_not_count_as_cardc_confirmed(cardc_db_path):
    checker = LogStatusChecker(cardc_db_path, "qso_table_v008")
    status = checker.lookup("7X3DEF", band="40M", mode="FT8")
    assert status.confirmed_ever is True  # CONFIRMED_LIKE counts eQSL
    assert status.confirmed_lotw_or_card_ever is False  # neither LoTW nor CardC
    assert status.status_for_scope(True, False) == "worked"  # not "confirmed"


def test_entity_status_scoped_index_treats_cardc_as_confirmed(cardc_db_path):
    checker = LogStatusChecker(cardc_db_path, "qso_table_v008")
    checker.refresh_worked_sets()
    scopes = checker.entity_status_all_scopes(400, "20M", "FT8")
    assert scopes["band"] == "confirmed"

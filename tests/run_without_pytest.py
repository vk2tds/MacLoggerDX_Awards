"""No-pytest test runner (sandbox has no network access to pip install
pytest). Mirrors what `pytest tests/` would do: run every test_* function
in test_wsjtx_udp.py, test_ft8_parser.py, test_dxcc_lookup.py directly
(no fixtures needed there), and hand-roll the db_path/tmp_path fixtures
for test_log_status.py. If you have pytest available, just run
`pytest tests/` instead -- this file is only a fallback.
"""
import os
import sqlite3
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

passed = 0
failed = 0


def run(name, fn, *args):
    global passed, failed
    try:
        fn(*args)
        print(f"PASS  {name}")
        passed += 1
    except Exception:
        print(f"FAIL  {name}")
        traceback.print_exc()
        failed += 1


def run_simple_module(modname):
    mod = __import__(modname)
    for attr in dir(mod):
        if attr.startswith("test_"):
            run(f"{modname}.{attr}", getattr(mod, attr))


run_simple_module("test_wsjtx_udp")
run_simple_module("test_ft8_parser")
run_simple_module("test_dxcc_lookup")
run_simple_module("test_qsl_helper")
run_simple_module("test_live_monitor_reply")
run_simple_module("test_qso_queue")
run_simple_module("test_macloggerdx_bridge")

# -- test_log_status.py, with hand-rolled fixtures --
import test_log_status as tls  # noqa: E402


def make_db():
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
    return path


for fn_name in (
    "test_schema_introspection",
    "test_lookup_never_worked",
    "test_lookup_worked_before",
    "test_lookup_worked_different_band_not_confirmed",
    "test_lookup_by_base_callsign_for_portable",
    "test_worked_sets_and_new_dxcc_flag",
):
    db_path = make_db()
    try:
        run(f"test_log_status.{fn_name}", getattr(tls, fn_name), db_path)
    finally:
        os.unlink(db_path)

tmp_dir = tempfile.mkdtemp()
try:
    import pathlib
    run("test_log_status.test_missing_database_reports_error_not_crash",
        tls.test_missing_database_reports_error_not_crash, pathlib.Path(tmp_dir))
finally:
    os.rmdir(tmp_dir)

# -- test_log_writer.py, with hand-rolled fixtures --
import test_log_writer as tlw  # noqa: E402


def make_writer_db():
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
    return path


for fn_name in (
    "test_insert_qso_writes_expected_row",
    "test_insert_qso_leaves_distance_unset_matching_short_grid_convention",
    "test_find_possible_duplicate_detects_recent_same_call_band_mode",
    "test_find_possible_duplicate_ignores_old_or_different_contact",
):
    wdb_path = make_writer_db()
    try:
        run(f"test_log_writer.{fn_name}", getattr(tlw, fn_name), wdb_path)
    finally:
        os.unlink(wdb_path)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)

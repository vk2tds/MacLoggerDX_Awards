import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import macloggerdx_bridge as bridge

REC = dict(
    my_call="VK2TDS", my_grid="QF55KX", call="JA1ABC", grid="PM95",
    mode="FT8", band="20M", tx_frequency_mhz=14.074,
    rst_sent="-10", rst_received="-12",
    qso_start=1700000000.0, qso_done=1700000060.0,
    comments="",
)


def test_build_adif_record_has_expected_fields_and_terminator():
    adif = bridge.build_adif_record(REC)
    assert adif.endswith("<EOR>")
    assert "<CALL:6>JA1ABC" in adif
    assert "<MODE:3>FT8" in adif
    assert "<BAND:3>20M" in adif
    assert "<STATION_CALLSIGN:6>VK2TDS" in adif
    assert "<FREQ:9>14.074000" in adif


def test_build_adif_record_uses_utc_date_time():
    adif = bridge.build_adif_record(REC)
    # 1700000000 UTC == 2023-11-14 22:13:20 UTC
    assert "<QSO_DATE:8>20231114" in adif
    assert "<TIME_ON:6>221320" in adif


def test_build_adif_record_omits_blank_fields():
    rec = dict(REC)
    rec["comments"] = ""
    rec["grid"] = ""
    adif = bridge.build_adif_record(rec)
    assert "<COMMENT" not in adif
    assert "<GRIDSQUARE" not in adif


def test_build_adif_record_omits_dxcc_and_cq_zone():
    # Deliberate: MacLoggerDX derives these itself from CALL, and WSJT-X's
    # own QSOLogged message (MacLoggerDX's other working QSO source)
    # doesn't carry them either.
    rec = dict(REC, dxcc_country="Japan", dxcc_id=339, cq_zone="25")
    adif = bridge.build_adif_record(rec)
    assert "DXCC" not in adif
    assert "CQZ" not in adif


def test_applescript_quote_escapes_quotes_and_backslashes():
    quoted = bridge._applescript_quote('He said "hi" \\ bye')
    assert quoted == '"He said \\"hi\\" \\\\ bye"'


class _patched_run:
    """Manual stand-in for pytest's monkeypatch fixture (not available in
    the no-pytest sandbox runner) -- swaps subprocess.run for the duration
    of a `with` block and restores it afterwards even on failure."""

    def __init__(self, fake):
        self.fake = fake
        self.original = None

    def __enter__(self):
        self.original = bridge.subprocess.run
        bridge.subprocess.run = self.fake
        return self

    def __exit__(self, *exc):
        bridge.subprocess.run = self.original


def test_send_adif_success():
    def fake_run(cmd, capture_output, text, timeout):
        assert cmd[0] == "osascript"
        assert "importADIF" in cmd[2]
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    with _patched_run(fake_run):
        ok, msg = bridge.send_adif_to_macloggerdx("<CALL:6>JA1ABC<EOR>")
    assert ok is True
    assert msg == "ok"


def test_send_adif_nonzero_exit_reports_stderr():
    def fake_run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="MacLoggerDX got an error")

    with _patched_run(fake_run):
        ok, msg = bridge.send_adif_to_macloggerdx("<CALL:6>JA1ABC<EOR>")
    assert ok is False
    assert "MacLoggerDX got an error" in msg


def test_send_adif_timeout():
    def fake_run(cmd, capture_output, text, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    with _patched_run(fake_run):
        ok, msg = bridge.send_adif_to_macloggerdx("<CALL:6>JA1ABC<EOR>")
    assert ok is False
    assert "Timed out" in msg

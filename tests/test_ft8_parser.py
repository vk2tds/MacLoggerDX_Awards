import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ft8_parser import parse_message, base_callsign


def test_cq_simple():
    p = parse_message("CQ VK2ABC QF56")
    assert p.is_cq
    assert p.de_call == "VK2ABC"
    assert p.grid == "QF56"
    assert p.cq_directed is None
    assert p.call_area == "2"


def test_cq_directed_dx():
    p = parse_message("CQ DX VK2ABC QF56")
    assert p.is_cq
    assert p.cq_directed == "DX"
    assert p.de_call == "VK2ABC"
    assert p.grid == "QF56"


def test_cq_directed_call_area():
    p = parse_message("CQ 6 W6XYZ CM87")
    assert p.is_cq
    assert p.cq_directed == "6"
    assert p.de_call == "W6XYZ"


def test_grid_exchange():
    p = parse_message("VK2ABC W1AW FN31")
    assert not p.is_cq
    assert p.to_call == "VK2ABC"
    assert p.de_call == "W1AW"
    assert p.grid == "FN31"
    assert p.subject_call == "W1AW"


def test_report_exchange():
    p = parse_message("W1AW VK2ABC -14")
    assert p.de_call == "VK2ABC"
    assert p.report == "-14"


def test_r_report_exchange():
    p = parse_message("VK2ABC W1AW R-09")
    assert p.report == "R-09"


def test_rr73():
    p = parse_message("W1AW VK2ABC RR73")
    assert p.is_rr73
    assert not p.is_rrr
    assert not p.is_73


def test_73():
    p = parse_message("VK2ABC W1AW 73")
    assert p.is_73


def test_hashed_call():
    p = parse_message("CQ <...> QF56")
    assert p.is_cq
    assert p.hashed
    assert p.de_call is None


def test_empty_message_does_not_raise():
    p = parse_message("")
    assert p.raw == ""
    assert p.de_call is None


def test_free_text_does_not_raise():
    p = parse_message("TNX FOR QSO 73 GL")
    # Shouldn't crash; fields may be partially populated depending on tokens.
    assert p.raw == "TNX FOR QSO 73 GL"


def test_base_callsign_portable():
    assert base_callsign("VK2ABC/P") == "VK2ABC"


def test_base_callsign_dxpedition_prefix():
    assert base_callsign("3D2/VK2ABC") == "VK2ABC"


def test_base_callsign_plain():
    assert base_callsign("VK2ABC") == "VK2ABC"


def test_base_callsign_none():
    assert base_callsign(None) is None

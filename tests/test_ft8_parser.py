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


def test_hashed_but_resolved_call_strips_brackets():
    # WSJT-X wraps a callsign in "<...>" when it went through the
    # compressed/hashed-callsign message slot -- unlike the literal "<...>"
    # placeholder, this brackets a real, already-decoded callsign and
    # should be treated exactly like a plain token, brackets stripped.
    p = parse_message("<V4/SP9FIH> VK2TDS QF55")
    assert p.to_call == "V4/SP9FIH"
    assert p.de_call == "VK2TDS"
    assert not p.hashed

    p2 = parse_message("VK2TDS <BV400> -21")
    assert p2.to_call == "VK2TDS"
    assert p2.de_call == "BV400"
    assert not p2.hashed


def test_bare_ack_token_is_not_a_callsign():
    # Regression: a decode consisting of just "RR73"/"RRR"/"73" with no
    # visible TO/DE (WSJT-X can decode a bare ack alone when that frame's
    # callsigns are hashed/unresolved) was being treated as a single-token
    # callsign by the free-text fallback, since e.g. "RR73" superficially
    # matches CALL_RE's loose letter-digit-letter shape -- DX Monitor was
    # showing "RR73" grouped as if it were a real station. A bare ack
    # carries no reliable callsign information, so it should parse to no
    # callsign at all, same as any other unparseable single token.
    for word in ("RR73", "RRR", "73"):
        p = parse_message(word)
        assert p.subject_call is None, f"{word} -> {p.subject_call}"
        assert p.de_call is None

    # Also covers a punctuated variant (e.g. "RR73;"), in case a low-
    # confidence decode ever includes trailing punctuation.
    p = parse_message("RR73;")
    assert p.subject_call is None


def test_ack_token_in_to_de_position_is_not_a_callsign():
    # Regression: the single-token fix above didn't cover this -- a
    # garbled/low-confidence decode can put an ack token in the TO or DE
    # slot of what otherwise looks like an ordinary 2/3-token exchange.
    # _resolve_call_token() (used for both TO/DE and the CQ branch's call
    # slot) didn't validate its token's shape at all, so "RR73;" sitting in
    # that position was accepted verbatim as a real callsign -- a real
    # DX Monitor report: "European Russia" with "RR73;" grouped as if it
    # were an actual station, heard for a real decode's worth of activity.
    p = parse_message("R7CD RR73;")
    assert p.de_call is None
    assert p.subject_call is None
    assert p.to_call == "R7CD"  # the *other* token is still a real callsign

    p2 = parse_message("RR73; R7CD")
    assert p2.to_call is None
    assert p2.de_call == "R7CD"
    assert p2.subject_call == "R7CD"

    # A real 3-token exchange (ack as the trailing token, not TO/DE) must
    # still work exactly as before.
    p3 = parse_message("R7CD RJ3DC RR73")
    assert p3.to_call == "R7CD"
    assert p3.de_call == "RJ3DC"
    assert p3.subject_call == "RJ3DC"
    assert p3.is_rr73


def test_garbled_message_salvages_bracketed_call_elsewhere_in_text():
    # Regression (live 2026-08-15): two transmissions decoded as one
    # garbled string, "KE6FV RR73; VE2WNF <TN8GD> -16" -- the real DE slot
    # ("RR73;") collided with an ack token so subject_call would otherwise
    # be dropped entirely, same as test_ack_token_in_to_de_position_is_not_a_callsign.
    # But "<TN8GD>" elsewhere in the message is WSJT-X's own confident
    # decode of a real callsign (not a guess), so it should be salvaged.
    p = parse_message("KE6FV RR73; VE2WNF <TN8GD> -16")
    assert p.to_call == "KE6FV"
    assert p.de_call is None
    assert p.subject_call == "TN8GD"


def test_garbled_cq_message_salvages_bracketed_call():
    # Same ack-token collision as above, but in the CQ branch's call slot.
    p = parse_message("CQ RR73; <TN8GD>")
    assert p.is_cq
    assert p.de_call is None
    assert p.subject_call == "TN8GD"


def test_garbled_message_without_bracket_stays_unresolved():
    # No bracketed call anywhere in this one (unlike the case above) --
    # nothing reliable to salvage, so it must stay unresolved rather than
    # guessing at a plain token (that's exactly what
    # test_ack_token_in_to_de_position_is_not_a_callsign already covers,
    # and this fallback must not reopen it).
    p = parse_message("SP0DF RR73; JR7ANB -18")
    assert p.subject_call is None


def test_free_text_signoff_word_in_de_slot_is_not_a_callsign():
    # Regression (live 2026-08-19): "73 TNX QSO" -- a plain free-text
    # sign-off ("thanks for the QSO"), not a structured TO/DE exchange --
    # decoded with "73" correctly rejected from the TO slot (an ack token)
    # but "TNX" landing in the DE slot and getting accepted as a real
    # callsign verbatim, since ACK_TOKENS only covers RRR/RR73/73. DX
    # Monitor showed a station literally named "TNX" grouped under
    # Republic of the Congo. No digit anywhere in "TNX" -- no real
    # callsign has none -- so it must be rejected the same way an ack
    # token already is.
    p = parse_message("73 TNX QSO")
    assert p.to_call is None
    assert p.de_call is None
    assert p.subject_call is None

    p2 = parse_message("73 TNX JON")
    assert p2.subject_call is None

    # Real callsigns must still resolve fine either side of the slash-free
    # digit check.
    p3 = parse_message("VK2ABC W1AW FN31")
    assert p3.to_call == "VK2ABC"
    assert p3.de_call == "W1AW"


def test_bare_signal_report_in_de_slot_is_not_a_callsign():
    # Regression (live 2026-08-30): the digit-only version of the free-text
    # check above still let a bare signal report through -- it has digits,
    # just not letters -- so "F6DZU +00" logged a station literally named
    # "+00" as an unknown DXCC call.
    p = parse_message("F6DZU +00")
    assert p.subject_call is None
    p2 = parse_message("VK2ABC -11")
    assert p2.subject_call is None


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

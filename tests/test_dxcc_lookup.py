import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dxcc_lookup import DxccResolver, _expand_prefix_field

FIXTURE = os.path.join(os.path.dirname(__file__), "fixture_dxcc.txt")


def test_expand_simple_literal():
    assert _expand_prefix_field("F") == [("literal", "F")]


def test_expand_range():
    assert _expand_prefix_field("K,W,N,AA-AK#") == [
        ("literal", "K"), ("literal", "W"), ("literal", "N"), ("range", "AA", "AK"),
    ]


def test_expand_continuation_shorthand():
    assert _expand_prefix_field("9M2,4(8)") == [("literal", "9M2"), ("literal", "9M4")]


def test_expand_two_unrelated_literals_not_mistaken_for_shorthand():
    # Regression (live 2026-08-30): the continuation-shorthand rule above
    # (a shorter token after a longer one replaces the longer one's
    # trailing characters, e.g. "9M2,4" -> "9M2","9M4") mis-fired on two
    # genuinely unrelated literals that just happen to have one shorter
    # than the other -- "4U1UN,4U1A" silently expanded to
    # "4U1UN","44U1A" (4U1UN's last 4 chars replaced by "4U1A") instead of
    # two independent literals, so "4U1A" (the UN's Vienna office) never
    # resolved at all. Putting the shorter one first avoids the shorthand
    # path entirely (its own length check requires the *later* token to be
    # shorter, not the earlier one) -- confirm both orderings behave as
    # expected so this can't quietly regress the other way either.
    assert _expand_prefix_field("4U1A,4U1UN") == [("literal", "4U1A"), ("literal", "4U1UN")]
    assert _expand_prefix_field("4U1UN,4U1A") == [("literal", "4U1UN"), ("literal", "44U1A")]


def test_expand_dash_continuation_shorthand():
    # Nicaragua: "H6-7" means H6..H7, not a literal "H6" plus a bogus
    # single-digit literal "7" (which would then wrongly match any call
    # starting with "7", including Japan's 7J-7N block).
    assert _expand_prefix_field("YN,H6-7") == [("literal", "YN"), ("range", "H6", "H7")]


def test_expand_digit_prefixed_range():
    # Japan: "7J-7N" is a regular equal-length range, just digit-prefixed --
    # it was falling through to a bare "literal 7J" because the old code
    # only recognised pure-alphabetic equal-length ranges.
    assert _expand_prefix_field("JA-JS,7J-7N") == [
        ("range", "JA", "JS"), ("range", "7J", "7N"),
    ]


def test_resolver_loads_fixture():
    r = DxccResolver(FIXTURE)
    assert len(r.entities) == 24


def test_lookup_japan_digit_prefixed_range_not_nicaragua():
    # Regression: 7K/7L/7M/7N calls were resolving to Nicaragua (whose
    # "H6-7" range was mis-parsed into a bogus single-digit literal "7",
    # which happened to out-match Japan's mis-parsed "7J-7N" -> literal "7J").
    r = DxccResolver(FIXTURE)
    for call in ("7J1ADJ", "7K1UPA", "7K4AIS", "7L1ABC", "7M1ABC", "7N1ABC"):
        ent = r.lookup(call)
        assert ent is not None and ent.name == "Japan", f"{call} -> {ent}"


def test_lookup_nicaragua_dash_continuation():
    r = DxccResolver(FIXTURE)
    assert r.lookup("H6ABC").name == "Nicaragua"
    assert r.lookup("H7ABC").name == "Nicaragua"


def test_lookup_simple_prefix():
    r = DxccResolver(FIXTURE)
    ent = r.lookup("F5ABC")
    assert ent is not None
    assert ent.name == "France"


def test_lookup_longest_prefix_wins():
    r = DxccResolver(FIXTURE)
    australia = r.lookup("VK2ABC")
    cocos = r.lookup("VK9XYZ")
    assert australia.name == "Australia"
    assert cocos.name == "Cocos (Keeling) Is."
    assert australia.dxcc_id != cocos.dxcc_id


def test_lookup_usa_range():
    r = DxccResolver(FIXTURE)
    ent = r.lookup("W1AW")
    assert ent is not None
    assert ent.name == "United States of America"
    # AA-AK range should also resolve
    ent2 = r.lookup("AA1AA")
    assert ent2 is not None
    assert ent2.name == "United States of America"


def test_lookup_continuation_shorthand():
    r = DxccResolver(FIXTURE)
    west = r.lookup("9M2ABC")
    east = r.lookup("9M4ABC")
    assert west.name == "West Malaysia"
    assert east.name == "West Malaysia"  # 9M4 belongs to West Malaysia per the fixture


def test_lookup_unknown_prefix_returns_none():
    r = DxccResolver(FIXTURE)
    assert r.lookup("ZZZZZZ") is None


def test_lookup_handles_slash_calls():
    r = DxccResolver(FIXTURE)
    ent = r.lookup("F5ABC/P")
    assert ent is not None
    assert ent.name == "France"


def test_lookup_empty_input():
    r = DxccResolver(FIXTURE)
    assert r.lookup("") is None
    assert r.lookup(None) is None


def test_lookup_russia_splits_by_call_area_digit():
    # Regression: European Russia and Asiatic Russia both list the exact
    # same "RA-RZ" range (and, once expanded, the same bare "UA"/"UI"
    # literals) -- the generic literal/range rules can't tell them apart,
    # so European always won ties. Bare "R"+digit calls (R7DX) didn't
    # resolve at all under the generic rules either.
    r = DxccResolver(FIXTURE)
    european = ("R1ABC", "R7DX", "RA3ABC", "UA3ABC", "UI1ABC")
    asiatic = ("R8ABC", "R9ABC", "R0ABC", "RA9ABC", "RZ0ABC", "UA9ABC", "UI8ABC")
    for call in european:
        ent = r.lookup(call)
        assert ent is not None and ent.name == "European Russia", f"{call} -> {ent}"
    for call in asiatic:
        ent = r.lookup(call)
        assert ent is not None and ent.name == "Asiatic Russia", f"{call} -> {ent}"


def test_lookup_kg4_two_letter_suffix_is_guantanamo():
    # Regression: dxcc.txt's "KG4#" prefix, taken literally, out-matches
    # USA's own "K" for every KG4 call regardless of suffix length. Real
    # ARRL rule: only a two-letter KG4 suffix is Guantanamo Bay.
    r = DxccResolver(FIXTURE)
    assert r.lookup("KG4AB").name == "Guantanamo Bay"
    assert r.lookup("KG4XY").name == "Guantanamo Bay"


def test_lookup_kg4_one_or_three_letter_suffix_is_usa():
    # Regression: KG4OJT (grid FM18 -- mainland Virginia/NC) was
    # misresolving to Guantanamo Bay before this fix.
    r = DxccResolver(FIXTURE)
    assert r.lookup("KG4OJT").name == "United States of America"
    assert r.lookup("KG4A").name == "United States of America"


def test_lookup_uk_modern_m_and_2e_prefixes():
    # Regression: M0UOO (IO90, real-world England station) resolved to no
    # entity at all -- the raw ARRL dxcc.txt only lists "G" for England,
    # missing the modern second-generation "M0"/"2E0" etc. callsign blocks
    # issued since 2003. Fixed by adding M/2E to dxcc.txt's prefix field.
    r = DxccResolver(FIXTURE)
    assert r.lookup("M0UOO").name == "United Kingdom of Great Britain"
    assert r.lookup("2E0ABC").name == "United Kingdom of Great Britain"
    assert r.lookup("G0ABC").name == "United Kingdom of Great Britain"


def test_lookup_vk0_antarctica_by_grid():
    # Regression (live 2026-08-16): VK0DS decoded with grid MC81 (~68.5S
    # 78E, right at Davis Station) was resolving to "Heard I." -- an
    # arbitrary tie-break, since Heard I. and Macquarie I. both list the
    # identical "VK0#" prefix and Antarctica's own footnote separately
    # documents VK0 as one of many home-country prefixes used by Antarctic
    # stations. South of 60S (ARRL's own Antarctica boundary) should always
    # win regardless of longitude.
    r = DxccResolver(FIXTURE)
    assert r.lookup("VK0DS", grid="MC81").name == "Antarctica"
    assert r.lookup("VK0MAW", grid="MC12").name == "Antarctica"  # Mawson Station


def test_lookup_vk0_heard_vs_macquarie_by_grid():
    r = DxccResolver(FIXTURE)
    assert r.lookup("VK0EK", grid="MD66").name == "Heard I."       # ~53S 73E
    assert r.lookup("VK0MC", grid="QD95").name == "Macquarie I."   # ~54.5S 159E


def test_lookup_vk0_without_grid_keeps_default():
    # No grid to disambiguate with -- can't do better than the pre-existing
    # arbitrary default, but must still resolve to *something* rather than
    # regressing to no match at all.
    r = DxccResolver(FIXTURE)
    assert r.lookup("VK0XX").name == "Heard I."


def test_lookup_russia_full_ua_ui_range_not_just_endpoints():
    # Regression (live 2026-08-30): dxcc.txt's real entry is "UA-UI1-7" --
    # the *range* UA through UI -- but the special-case regex only ever
    # matched the literal strings "UA" and "UI", silently dropping every
    # call using UB/UC/UD/UE/UF/UG/UH. Surfaced via a large, sustained
    # cluster of U[B-F]-prefixed calls in the "Unknown DXCC callsigns" log
    # (dozens of genuinely different Russian stations, not noise).
    r = DxccResolver(FIXTURE)
    for call, expected in (
        ("UB0IBA", "Asiatic Russia"),   # area 0 -> Asiatic
        ("UC6D", "European Russia"),    # area 6 -> European
        ("UD6X", "European Russia"),
        ("UE3ABC", "European Russia"),
        ("UF1A", "European Russia"),
        ("UG3ABC", "European Russia"),
        ("UH8ABC", "Asiatic Russia"),   # area 8 -> Asiatic
    ):
        ent = r.lookup(call)
        assert ent is not None and ent.name == expected, f"{call} -> {ent}"
    # Must NOT bleed past the range into Uzbekistan's adjacent UJ-UM block
    # -- this fixture doesn't carry Uzbekistan, so a real mismatch here
    # would show up as an unexpected resolve, not just a wrong one.
    assert r.lookup("UJ8ABC") is None


def test_lookup_special_event_and_secondary_prefixes():
    # Regression (live 2026-08-30): several mainstream countries' second
    # prefix blocks -- widely used for special-event/contest stations, not
    # exotic edge cases -- were missing from dxcc.txt entirely, discovered
    # the same way as the Russia gap above (a real decode showing up in
    # the unknown-DXCC log, then confirmed against the country's actual
    # ITU allocation before fixing, same as every other prefix fix this
    # session).
    r = DxccResolver(FIXTURE)
    checks = {
        "9W2BAF": "West Malaysia", "9W6ABC": "East Malaysia",  # modern MY prefix, not just 9M
        "TM6KJS": "France",                                     # French special-event stations
        "8J1HAM": "Japan", "8N3AZ": "Japan",                    # Japanese special-event stations
        "VJ2Q": "Australia", "VL4A": "Australia",               # AU special-event (VH-VN range)
        "7Z1CZ": "Saudi Arabia",
        "5P5Z": "Denmark", "5Q1ABC": "Denmark",
        "3E40CDW": "Panama", "3F1ABC": "Panama",
        "3G1DX": "Chile", "XQ1CY": "Chile", "XR3ABC": "Chile",
        "HF8E": "Poland", "3Z0YL": "Poland",
        "AO5FSB": "Spain",
    }
    for call, expected in checks.items():
        ent = r.lookup(call)
        assert ent is not None and ent.name == expected, f"{call} -> {ent}"


def test_lookup_un_hq_vienna_and_new_york_both_resolve():
    # Regression (live 2026-08-30): dxcc.txt's ITU HQ/UN HQ entries used
    # literal "4U_ITU"/"4U_UN" placeholders (an underscore isn't a valid
    # callsign character) that could never match any real callsign at all.
    # Fixed to real literals, and 4U1A (the UN's Vienna office, per the
    # user) added alongside 4U1UN under the same "United Nations HQ"
    # entity -- see test_expand_two_unrelated_literals_not_mistaken_for_shorthand
    # for the token-order gotcha hit getting this in correctly.
    r = DxccResolver(FIXTURE)
    assert r.lookup("4U1ITU").name == "ITU HQ"
    assert r.lookup("4U1UN").name == "United Nations HQ"
    assert r.lookup("4U1A").name == "United Nations HQ"

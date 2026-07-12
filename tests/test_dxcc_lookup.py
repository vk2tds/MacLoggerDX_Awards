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
    assert len(r.entities) == 9


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

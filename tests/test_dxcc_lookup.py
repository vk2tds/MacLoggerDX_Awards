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


def test_resolver_loads_fixture():
    r = DxccResolver(FIXTURE)
    assert len(r.entities) == 8


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

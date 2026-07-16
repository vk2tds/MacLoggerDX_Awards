#!/usr/bin/env python3
"""
dxcc_lookup.py -- Best-effort callsign -> DXCC entity / continent / CQ zone
resolver, built from the same ARRL DXCC list text file (dxcc.txt) that
macloggerdx_awards.py already downloads and parses (see its
`doGetDXCC_Continent` method, whose line-matching regex this module reuses
verbatim so both stay in sync with the same file format).

IMPORTANT -- this is advisory only. ARRL's "Prefix" column uses a compact,
sometimes ambiguous shorthand (comma lists, alphabetic ranges, nested call-
area ranges like "UA-UI1-7") that genuinely requires a hand-curated
country file (like Club Log's cty.dat) to resolve with 100% accuracy --
notably for Russia/Asiatic Russia, China, and a handful of others.

This resolver is meant for one job: flagging *possibly* new/unworked
DXCC/continent/CQ-zone for a callsign we've just heard on the air, live, so
we can highlight it -- not for award-qualifying determinations. The
authoritative record stays your MacLoggerDX log (which already has a
proper dxcc_id looked up at logging time). When in doubt this module
prefers to under-claim (return no match) rather than guess wrong.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import re
import urllib.request
from typing import Optional

log = logging.getLogger("dxcc_lookup")

# Identical to macloggerdx_awards.analysis.doGetDXCC_Continent's regex, so a
# dxcc.txt that works for the awards tracker also works here.
_TABLE_TOP_RE = re.compile("[_ ]+")
_EMPTY_LINE_RE = re.compile(" *")
_DATA_LINE_RE = re.compile(
    r"\s+([0-9A-Z,_\-\/]+)"
    r"(?:\#?\*?\(\d+\),?)*\#?\^?\*?\s+"
    r"(.*?)\s+"
    r"([A-Z]{2}(?:,[A-Z]{2})?)\s+"
    r"(\d{2}(?:[,\-]\d{2})?|\([A-Z]\))\s+"
    r"(\d{2}(?:[,\-]\d{2})?|\([A-Z]\))\s+0*(\d+?)(?:\s*?)"
)

DEFAULT_DXCC_URI = "http://www.arrl.org/files/file/DXCC/2019_Current_Deleted(3).txt"


@dataclasses.dataclass
class Entity:
    dxcc_id: int
    name: str
    continent: str
    itu_zone: str
    cq_zone: str
    prefix_field: str


@dataclasses.dataclass
class PrefixRule:
    """One literal prefix or alphabetic range, pointing at its Entity."""
    entity: Entity
    literal: Optional[str] = None       # e.g. "VK", "3A"
    range_lo: Optional[str] = None      # e.g. "AA"
    range_hi: Optional[str] = None      # e.g. "AK"


def _strip_footnotes(field: str) -> str:
    field = re.sub(r"\(\d+\)", "", field)
    return field.strip(" #^*")


def _expand_prefix_field(field: str) -> list:
    """
    Turn an ARRL "Prefix" column value into a list of (literal | range) tokens.
    Handles the common cases well: comma-separated literals, comma-separated
    ranges ("AA-AK"), and short continuation tokens that inherit the stem of
    the previous token (e.g. "9M2,4" -> "9M2", "9M4"; "3B6,7" -> "3B6", "3B7").
    Leaves genuinely irregular nested-range notation (e.g. "UA-UI1-7") as a
    single literal token (the text before the first '-') rather than
    guessing -- better to under-match than mis-match.
    """
    field = _strip_footnotes(field)
    tokens = []
    prev_stem = None
    for raw in field.split(","):
        tok = raw.strip()
        if not tok:
            continue
        if "-" in tok:
            lo, _, hi = tok.partition("-")
            lo, hi = lo.strip(), hi.strip()
            # Shorthand range where hi is just the trailing character(s) of
            # lo, e.g. "H6-7" (Nicaragua: H6..H7) or "9M2-4" (H6, H7) -- hi
            # replaces the trailing characters of lo, same idea as the
            # comma continuation-shorthand below but written with a dash.
            if hi and lo and len(hi) < len(lo) and hi.isalnum():
                hi_full = lo[: -len(hi)] + hi
                tokens.append(("range", lo.upper(), hi_full.upper()))
                prev_stem = lo[: -len(hi)]
                continue
            # Equal-length alphanumeric range, e.g. "AA-AK" (pure alpha) or
            # "7J-7N" / "5C-5G" (digit-prefixed call-area ranges like Japan
            # or Morocco) -- both ends vary only in the trailing letter(s).
            if lo and hi and len(lo) == len(hi) and lo.isalnum() and hi.isalnum():
                lo_u, hi_u = lo.upper(), hi.upper()
                diff = [i for i in range(len(lo_u)) if lo_u[i] != hi_u[i]]
                if len(diff) == 1 and diff[0] != len(lo_u) - 1:
                    # The varying character is in the middle, not at the end
                    # -- e.g. "EA6-EH6" means EA6/EB6/.../EH6 (Balearic Is.),
                    # NOT "everything lexicographically between EA6 and EH6".
                    # That distinction matters: EA8 falls inside the naive
                    # lexicographic range [EA6, EH6] (same first character,
                    # 'A' <= 'A' <= 'H') even though EA8 is Canary Islands'
                    # own distinct prefix ("EA8-EH8", a separate entity) --
                    # a real mismatch this exact case caused. A true
                    # lexicographic range only makes sense when the *last*
                    # character is what varies, so expand this one
                    # explicitly into one literal token per character
                    # instead of treating lo/hi as range bounds.
                    pos = diff[0]
                    for code in range(ord(lo_u[pos]), ord(hi_u[pos]) + 1):
                        tokens.append(("literal", lo_u[:pos] + chr(code) + lo_u[pos + 1:]))
                    prev_stem = lo_u[:-1]
                    continue
                tokens.append(("range", lo_u, hi_u))
                prev_stem = lo[:-1]
                continue
            # Anything else (nested/irregular notation like "UI1-7" embedded
            # in "UA-UI1-7", or differing-length compound prefixes like
            # "PP0-PY0F") is genuinely ambiguous -- treat conservatively as
            # two literal prefixes rather than guessing a range.
            tokens.append(("literal", lo))
            tokens.append(("literal", hi))
            prev_stem = lo
            continue

        if prev_stem and tok.isalnum() and len(tok) < len(prev_stem):
            # Continuation shorthand: replace the trailing characters of the
            # previous token with this one, e.g. "9M2,4" second token "4"
            # -> "9M" + "4" = "9M4"; "3B6,7" second token "7" -> "3B" + "7" = "3B7".
            new_literal = prev_stem[: -len(tok)] + tok
            tokens.append(("literal", new_literal))
            prev_stem = new_literal
            continue

        tokens.append(("literal", tok))
        prev_stem = tok
    return tokens


def load_entities(dxcc_file: str, dxcc_uri: str = DEFAULT_DXCC_URI) -> list:
    """Parse dxcc.txt into a flat list of Entity records (current list only;
    stops at the first blank line, same as macloggerdx_awards.py)."""
    if not os.path.exists(dxcc_file):
        log.info("Downloading DXCC list to %s", dxcc_file)
        urllib.request.urlretrieve(dxcc_uri, filename=dxcc_file)

    entities = []
    with open(dxcc_file, mode="r", encoding="UTF-8") as fh:
        text = fh.read()
        state = "SEARCHING_FOR_LIST"
        for line in text.splitlines():
            if state == "SEARCHING_FOR_LIST":
                if _TABLE_TOP_RE.fullmatch(line):
                    state = "TABLE"
            elif _EMPTY_LINE_RE.fullmatch(line):
                break
            else:
                m = _DATA_LINE_RE.fullmatch(line)
                if not m:
                    continue
                prefix_field, name, continent, itu, cq, dxcc_id = m.groups()
                entities.append(Entity(
                    dxcc_id=int(dxcc_id),
                    name=name.strip(),
                    continent=continent.split(",")[0],
                    itu_zone=itu,
                    cq_zone=cq,
                    prefix_field=prefix_field,
                ))
    return entities


class DxccResolver:
    def __init__(self, dxcc_file: str, dxcc_uri: str = DEFAULT_DXCC_URI):
        self.entities = load_entities(dxcc_file, dxcc_uri)
        self.rules: list = []
        for ent in self.entities:
            for tok in _expand_prefix_field(ent.prefix_field):
                if tok[0] == "literal":
                    self.rules.append(PrefixRule(entity=ent, literal=tok[1]))
                else:
                    self.rules.append(PrefixRule(entity=ent, range_lo=tok[1], range_hi=tok[2]))
        # Longest literal prefixes first so e.g. "VK9" beats "VK".
        self.rules.sort(key=lambda r: len(r.literal) if r.literal else 0, reverse=True)
        log.info("DXCC resolver loaded %d entities, %d prefix rules", len(self.entities), len(self.rules))

    def lookup(self, callsign: str) -> Optional[Entity]:
        """Best-effort longest-prefix-match lookup. Returns None if unsure."""
        if not callsign:
            return None
        call = callsign.strip().upper()
        # Ignore a leading DXpedition-style prefix override (e.g. "3D2/VK2ABC")
        # by preferring the part that looks most like the operating prefix:
        # for our purposes (identifying who's on the air right now) that's
        # generally the FIRST slash-part if it itself looks like a prefix
        # override, otherwise the base call.
        base = call.split("/")[0]

        best = None
        best_len = -1
        for rule in self.rules:
            if rule.literal:
                if base.startswith(rule.literal) and len(rule.literal) > best_len:
                    best = rule.entity
                    best_len = len(rule.literal)
            else:
                n = len(rule.range_lo)
                if len(base) >= n:
                    stem = base[:n]
                    if rule.range_lo <= stem <= rule.range_hi and n > best_len:
                        best = rule.entity
                        best_len = n
        return best

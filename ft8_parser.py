#!/usr/bin/env python3
"""
ft8_parser.py -- Parse the free-text "Message" field of a WSJT-X Decode
packet (standard FT8/FT4/MSK144 structured messages) into a callsign,
grid, report and CQ/ack flags.

This intentionally does NOT try to be a full re-implementation of WSJT-X's
message packer/unpacker (that involves the full 77-bit FT8 encoding table
and callsign hash lookups). Instead it parses the *decoded text* WSJT-X
already hands us over UDP, which for the standard messages is plain,
space-separated and well documented in the WSJT-X User Guide ("Standard
Messages" section):

    CQ [<directed>] <CALL> <GRID>          e.g. "CQ VK2ABC QF56"
                                                 "CQ DX VK2ABC QF56"
                                                 "CQ 6 VK2ABC QF56"   (call-area directed)
    <TO> <DE> <GRID>                       e.g. "VK2ABC W1AW FN31"
    <TO> <DE> <REPORT>                     e.g. "W1AW VK2ABC -14"
    <TO> <DE> R<REPORT>                    e.g. "VK2ABC W1AW R-09"
    <TO> <DE> RRR
    <TO> <DE> RR73
    <TO> <DE> 73

Compound/portable calls (VK2ABC/P, 3D2AG/MM), "<...>" hashed calls (WSJT-X
prints this when it can't fully resolve a compressed callsign from a single
transmission) and free-text messages are all handled without raising.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Optional

GRID_RE = re.compile(r"^[A-R]{2}[0-9]{2}([A-X]{2})?$")
REPORT_RE = re.compile(r"^R?[+-]\d{2}$")
ACK_TOKENS = {"RRR", "RR73", "73"}
# Tokens that can appear as the "directed" word in "CQ <directed> CALL GRID"
DIRECTED_WORDS = {
    "DX", "TEST", "POTA", "FD", "NA", "SA", "EU", "AS", "AF", "OC", "AN",
    "QRP", "RC",
}

# Bare callsign shape: 1-3 leading alnum, at least one digit somewhere,
# 1-4 trailing letters, optional /suffix or prefix. Loose on purpose --
# we'd rather over-accept than crash on legitimate exotic calls.
CALL_RE = re.compile(r"^[A-Z0-9]{1,4}\d[A-Z0-9]{0,4}(/[A-Z0-9]{1,4})?$", re.IGNORECASE)


@dataclasses.dataclass
class ParsedMessage:
    raw: str
    is_cq: bool = False
    cq_directed: Optional[str] = None       # e.g. "DX", "TEST", "6"
    to_call: Optional[str] = None
    de_call: Optional[str] = None           # the callsign that originated this transmission
    grid: Optional[str] = None
    report: Optional[str] = None
    is_rrr: bool = False
    is_rr73: bool = False
    is_73: bool = False
    hashed: bool = False                    # de_call was "<...>" (compressed/unresolved)
    call_area: Optional[str] = None         # digit extracted from de_call (or CQ call)
    subject_call: Optional[str] = None      # the callsign this decode is "about" (best guess)


def _call_area_digit(call: str) -> Optional[str]:
    """Extract the numeral from a callsign, e.g. VK2ABC -> '2', W1AW -> '1'."""
    if not call:
        return None
    m = re.search(r"\d", call.split("/")[0])
    return m.group(0) if m else None


def _strip_suffixes(call: str) -> str:
    """Drop portable/mobile suffixes like /P, /QRP, /MM but keep prefix overrides."""
    return call


def parse_message(raw: str) -> ParsedMessage:
    text = (raw or "").strip()
    result = ParsedMessage(raw=text)
    if not text:
        return result

    tokens = text.split()

    # Strip a trailing lone "<...>" style hash marker some clients append; the
    # real hashed-call case is when a token itself is exactly "<...>".
    if tokens and tokens[0] == "CQ":
        result.is_cq = True
        rest = tokens[1:]
        if not rest:
            return result
        if len(rest) >= 3:
            # CQ <directed> <CALL> <GRID>
            result.cq_directed = rest[0]
            call_tok, grid_tok = rest[1], rest[2]
        elif len(rest) == 2:
            call_tok, grid_tok = rest[0], rest[1]
        else:
            # "CQ <CALL>" with no grid
            call_tok, grid_tok = rest[0], None

        if call_tok == "<...>":
            result.hashed = True
        else:
            result.de_call = call_tok
        if grid_tok and GRID_RE.match(grid_tok):
            result.grid = grid_tok
        result.call_area = _call_area_digit(result.de_call) if result.de_call else None
        result.subject_call = result.de_call
        return result

    # Non-CQ: "<TO> <DE> [<GRID>|<REPORT>|RRR|RR73|73]"
    if len(tokens) >= 2:
        to_tok, de_tok = tokens[0], tokens[1]
        result.to_call = None if to_tok == "<...>" else to_tok
        if de_tok == "<...>":
            result.hashed = True
        else:
            result.de_call = de_tok

        if len(tokens) >= 3:
            tail = tokens[2]
            if tail in ACK_TOKENS:
                result.is_rrr = tail == "RRR"
                result.is_rr73 = tail == "RR73"
                result.is_73 = tail == "73"
            elif GRID_RE.match(tail):
                result.grid = tail
            elif REPORT_RE.match(tail):
                result.report = tail
            # else: unrecognised trailing token (e.g. free text) -- ignore

        result.call_area = _call_area_digit(result.de_call) if result.de_call else None
        result.subject_call = result.de_call
        return result

    # Single token or something unusual (free text, tuning signal, etc.)
    if len(tokens) == 1 and CALL_RE.match(tokens[0]):
        result.de_call = tokens[0]
        result.subject_call = tokens[0]
        result.call_area = _call_area_digit(tokens[0])

    return result


def base_callsign(call: Optional[str]) -> Optional[str]:
    """
    Strip portable/mobile/QRP suffixes and DXpedition-style prefixes down to
    the "home" callsign, e.g. "VK2ABC/P" -> "VK2ABC", "3D2/VK2ABC" -> "VK2ABC".
    This is a heuristic, not a full callsign grammar parser.
    """
    if not call:
        return call
    parts = call.split("/")
    if len(parts) == 1:
        return parts[0]
    # Pick the part that looks most like a full callsign (has both letters and digits,
    # and isn't a short well-known suffix like P, MM, QRP, a US call-area digit, etc.)
    suffix_like = {"P", "M", "MM", "AM", "QRP", "LGT", "A"}
    candidates = [p for p in parts if p not in suffix_like and re.search(r"\d", p) and re.search(r"[A-Z]", p, re.I)]
    if candidates:
        # Prefer the longer/more specific-looking candidate.
        return max(candidates, key=len)
    return parts[0]

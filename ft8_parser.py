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


def _is_ack_token(tok: Optional[str]) -> bool:
    return tok is not None and tok.rstrip(".,;:") in ACK_TOKENS


_CALLSIGN_CHARS_RE = re.compile(r"^[A-Z0-9/]+$", re.IGNORECASE)


def _looks_like_callsign(tok: str) -> bool:
    """Loose sanity check: every real amateur callsign contains at least one
    digit (the ITU prefix+digit+suffix convention) and consists only of
    letters/digits/a portable-prefix slash, so a token with no digit at all,
    or containing anything else, can't be one. Regression (live 2026-08-19):
    "73 TNX QSO" -- a plain free-text sign-off, not a structured exchange --
    was decoding with "TNX" landing in the DE slot and getting accepted as a
    real callsign (DX Monitor showed a station literally named "TNX" under
    Republic of the Congo), since ACK_TOKENS only covers RRR/RR73/73, not
    other common ham jargon (TNX, QSO, GL, GM, FB, UR, ...) that can end up
    there the same way. Deliberately NOT the full CALL_RE here -- that also
    caps the trailing "/suffix" at 4 characters, which would wrongly reject
    a legitimate compound call like "V4/SP9FIH" (a 6-character home call
    after the slash) -- see _resolve_call_token below.

    Regression (live 2026-08-30): the digit-only version of this check
    still let a bare signal report like "+00" through (it has digits, just
    not letters) -- "F6DZU +00" logged a station literally named "+00" as
    an unknown DXCC call. A real callsign never contains "+"/"-"/space, so
    require the whole token to be alnum-or-slash too, not just "has a
    digit somewhere"."""
    return bool(_CALLSIGN_CHARS_RE.match(tok)) and any(c.isdigit() for c in tok)


def _resolve_call_token(tok: Optional[str]) -> tuple:
    """WSJT-X wraps a callsign in "<...>" when it's sent via the compressed/
    hashed-callsign slot of the message. If the bracketed content is exactly
    "..." the callsign genuinely couldn't be resolved (unknown); otherwise
    the brackets just mark *how* it was sent, and the enclosed text (e.g.
    "<V4/SP9FIH>", "<BV400>") is a real, already-decoded callsign that
    should be treated like any other token, brackets stripped.

    Returns (callsign_or_None, was_unresolved_hash).

    Deliberately rejects ACK_TOKENS ("RRR"/"RR73"/"73", punctuation
    stripped) and any token with no digit at all (see
    _looks_like_callsign) here too, not just in parse_message()'s
    single-token fallback -- this function backs the TO/DE positions of
    ordinary exchanges and the CQ branch's call slot as well, and neither
    validated its token's shape at all otherwise, so a garbled/low-
    confidence decode whose TO or DE token happens to be an ack word or
    other non-callsign free text was being accepted verbatim as a real
    callsign (a real DX Monitor report: "RR73;"/"TNX" grouped under a DXCC
    entity as if either were an actual station -- the single-token fix
    alone didn't cover this since the bad token wasn't the *only* token in
    that decode, it was sitting in the TO/DE slot of what looked like an
    ordinary 2/3-token exchange)."""
    if tok is None:
        return None, False
    if tok == "<...>":
        return None, True
    if len(tok) >= 2 and tok[0] == "<" and tok[-1] == ">":
        inner = tok[1:-1]
        if _is_ack_token(inner) or not _looks_like_callsign(inner):
            return None, False
        return inner, False
    if _is_ack_token(tok) or not _looks_like_callsign(tok):
        return None, False
    return tok, False


def _first_bracketed_call(tokens: list) -> Optional[str]:
    """Two transmissions occasionally get decoded as one garbled string
    (e.g. "KE6FV RR73; VE2WNF <TN8GD> -16" -- the real DE slot collided
    with an ack token, but a *different* token later in the message is
    still a genuine WSJT-X compressed-callsign decode). Unlike a bare
    uppercase token, "<CALL>" is WSJT-X's own confident decode of a real
    callsign, not a guess -- safe to use even outside its normal TO/DE
    position, unlike scanning for any callsign-shaped token (which would
    just as happily "resolve" the TO station in a message where the real
    transmitting station is genuinely unknown -- see
    test_ack_token_in_to_de_position_is_not_a_callsign)."""
    for tok in tokens:
        clean = tok.rstrip(".,;:")
        if len(clean) >= 2 and clean[0] == "<" and clean[-1] == ">":
            call, _ = _resolve_call_token(clean)
            if call:
                return call
    return None


def parse_message(raw: str) -> ParsedMessage:
    text = (raw or "").strip()
    result = ParsedMessage(raw=text)
    if not text:
        return result

    tokens = text.split()

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

        result.de_call, result.hashed = _resolve_call_token(call_tok)
        if grid_tok and GRID_RE.match(grid_tok):
            result.grid = grid_tok
        result.call_area = _call_area_digit(result.de_call) if result.de_call else None
        result.subject_call = result.de_call
        if result.subject_call is None:
            salvaged = _first_bracketed_call(rest)
            if salvaged:
                result.subject_call = salvaged
                result.call_area = _call_area_digit(salvaged)
        return result

    # Non-CQ: "<TO> <DE> [<GRID>|<REPORT>|RRR|RR73|73]"
    if len(tokens) >= 2:
        to_tok, de_tok = tokens[0], tokens[1]
        result.to_call, hashed_to = _resolve_call_token(to_tok)
        result.de_call, hashed_de = _resolve_call_token(de_tok)
        result.hashed = hashed_to or hashed_de

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
        if result.subject_call is None:
            salvaged = _first_bracketed_call(tokens)
            if salvaged:
                result.subject_call = salvaged
                result.call_area = _call_area_digit(salvaged)
        return result

    # Single token or something unusual (free text, tuning signal, etc.).
    # Explicitly excludes ACK_TOKENS ("RRR"/"RR73"/"73") -- a bare
    # acknowledgment with no visible TO/DE (WSJT-X can decode one alone when
    # the callsigns in that particular frame are hashed/unresolved) happens
    # to superficially match CALL_RE's loose letter-digit-letter shape, and
    # was being grouped on DX Monitor as if "RR73" were itself a real
    # station -- a bare ack genuinely carries no reliable callsign
    # information, so leaving subject_call unset (dropping it, same as any
    # other unparseable decode) is correct here, not a regression.
    if len(tokens) == 1 and not _is_ack_token(tokens[0]) and CALL_RE.match(tokens[0]):
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

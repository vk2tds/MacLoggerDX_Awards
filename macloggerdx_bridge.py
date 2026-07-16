#!/usr/bin/env python3
"""
macloggerdx_bridge.py -- pushes a queued QSO (see qso_queue.py) into
MacLoggerDX via its native `importADIF` AppleScript command, instead of
writing to MacLoggerDX's SQLite log directly (confirmed unreliable -- a
test insert never persisted, even across a MacLoggerDX restart).

Reference: https://dogparksoftware.com/MacLoggerDX%20Help/mldxfc_script.html
    tell application "MacLoggerDX"
        importADIF adifText
    end tell

Deliberately omits DXCC/CQ zone fields -- MacLoggerDX derives those itself
from CALL (its own callbook is more authoritative than our simple prefix
resolver), and WSJT-X's own QSOLogged UDP message -- MacLoggerDX's other,
already-working QSO source -- doesn't carry them either, so this matches
that precedent.
"""

from __future__ import annotations

import datetime
import logging
import subprocess
from typing import Tuple

log = logging.getLogger("macloggerdx_bridge")


def _adif_field(name: str, value) -> str:
    if value is None or value == "":
        return ""
    s = str(value)
    return f"<{name}:{len(s)}>{s}"


def build_adif_record(rec: dict) -> str:
    """rec: same shape as a qso_queue entry (epoch-second qso_start/
    qso_done). Produces one ADIF record, no header -- MacLoggerDX's own
    importADIF example doesn't use one either."""
    now = datetime.datetime.now(datetime.timezone.utc)
    qso_start = rec.get("qso_start")
    qso_done = rec.get("qso_done")
    dt_on = datetime.datetime.fromtimestamp(qso_start, tz=datetime.timezone.utc) if qso_start else now
    dt_off = datetime.datetime.fromtimestamp(qso_done, tz=datetime.timezone.utc) if qso_done else dt_on

    freq = rec.get("tx_frequency_mhz")
    freq_str = f"{freq:.6f}" if isinstance(freq, (int, float)) else None

    fields = [
        _adif_field("CALL", rec.get("call")),
        _adif_field("GRIDSQUARE", rec.get("grid")),
        _adif_field("MODE", rec.get("mode")),
        _adif_field("BAND", rec.get("band")),
        _adif_field("RST_SENT", rec.get("rst_sent")),
        _adif_field("RST_RCVD", rec.get("rst_received")),
        _adif_field("QSO_DATE", dt_on.strftime("%Y%m%d")),
        _adif_field("TIME_ON", dt_on.strftime("%H%M%S")),
        _adif_field("QSO_DATE_OFF", dt_off.strftime("%Y%m%d")),
        _adif_field("TIME_OFF", dt_off.strftime("%H%M%S")),
        _adif_field("FREQ", freq_str),
        _adif_field("STATION_CALLSIGN", rec.get("my_call")),
        _adif_field("MY_GRIDSQUARE", rec.get("my_grid")),
        _adif_field("COMMENT", rec.get("comments")),
    ]
    return "".join(f for f in fields if f) + "<EOR>"


def _applescript_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def send_adif_to_macloggerdx(adif_text: str, timeout: float = 15.0) -> Tuple[bool, str]:
    """Runs MacLoggerDX's native importADIF command via osascript.

    macOS will show a one-time Automation permission prompt ("... wants to
    control MacLoggerDX") the first time this actually runs -- that's a
    native system dialog a human has to approve, it can't be scripted
    around from here.
    """
    script = f'tell application "MacLoggerDX" to importADIF {_applescript_quote(adif_text)}'
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "Timed out waiting for MacLoggerDX/osascript"
    except FileNotFoundError:
        return False, "osascript not found -- this only works on macOS"

    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "unknown osascript error").strip()
        log.warning("importADIF failed: %s", message)
        return False, message
    return True, (proc.stdout or "").strip()

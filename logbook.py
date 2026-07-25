#!/usr/bin/env python3
"""
logbook.py -- the "Logbook" tab: a manually-refreshed (not live/streaming)
view of the MacLoggerDX log itself, rather than the live WSJT-X decode feed
(live_monitor.py) or the award/DXCC-challenge rollups
(macloggerdx_awards.py). Two things:

    - Recent QSOs -- what you logged in roughly the last day.
    - Recent confirmations -- QSOs confirmed (LoTW or a physical card) in
      roughly the last few months, sorted by *confirmation* date, not QSO
      date -- e.g. an old QSO someone just uploaded to LoTW this week
      should show up near the top, not buried at its original QSO date.

Deliberately doesn't do a live-updating view or decade/year/month browsing
yet -- starting with the simplest useful version of this tab, per the
user's own framing (2026-07-25); those are a documented follow-up, not
missing/broken.

Read-only against MacLoggerDX's SQLite log, same connection convention as
log_status.py (mode=ro URI, short retry on OperationalError since MacLoggerDX
can be writing to it at the same time).
"""

from __future__ import annotations

import calendar
import logging
import re
import sqlite3
import subprocess
import time
from typing import Optional

from flask import Blueprint, jsonify, render_template, request

log = logging.getLogger("logbook")

logbook_bp = Blueprint("logbook", __name__, template_folder="templates")

_database_path: Optional[str] = None
_qso_table: Optional[str] = None

# LoTW/CardC dates embedded in qsl_received look like "LoTW:20230221" or
# "CardC:20250304", comma-separated when more than one tag applies (e.g.
# "LoTW:20230221, LoTW:20230312, eQSL.cc DownloadInBox:Y" -- a QSO can be
# reconfirmed more than once over time, hence "findall", not "search").
_CONFIRM_TAG_RE = re.compile(r"(LoTW|CardC)\s*:\s*(\d{8})", re.IGNORECASE)


def _connect() -> sqlite3.Connection:
    uri = f"file:{_database_path}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=5.0)


def _execute(sql: str, params: tuple = (), retry_attempts: int = 3, retry_delay_s: float = 0.15) -> list:
    last_exc = None
    for attempt in range(retry_attempts):
        try:
            conn = _connect()
            try:
                cur = conn.cursor()
                cur.execute(sql, params)
                return cur.fetchall()
            finally:
                conn.close()
        except sqlite3.OperationalError as exc:
            last_exc = exc
            time.sleep(retry_delay_s * (attempt + 1))
    raise last_exc


def _qsl_badge(qsl_received: Optional[str]) -> Optional[str]:
    """Best single label for display -- prefers LoTW/Card (what the rest of
    this app treats as "really" confirmed, see log_status.py) over a bare
    eQSL mention."""
    if not qsl_received:
        return None
    upper = qsl_received.upper()
    if "LOTW" in upper:
        return "LoTW"
    if "CARDC" in upper:
        return "Card"
    if "EQSL" in upper:
        return "eQSL"
    return None


def _first_worked_times() -> tuple:
    """(dxcc_id -> earliest qso_start ever, (dxcc_id, band_tx) -> earliest
    qso_start on that band) across the *whole* log -- used to mark a QSO as
    "new DXCC"/"new band" at the time it happened. Recomputed per call
    (no caching) -- at this log's scale (~5000 rows) a couple of GROUP BY
    queries are cheap, and correctness (never going stale) matters more
    than shaving a few ms, same philosophy as log_status.py's approach."""
    dxcc_rows = _execute(f"SELECT dxcc_id, MIN(qso_start) FROM {_qso_table} WHERE dxcc_id IS NOT NULL GROUP BY dxcc_id")
    band_rows = _execute(
        f"SELECT dxcc_id, band_tx, MIN(qso_start) FROM {_qso_table} "
        f"WHERE dxcc_id IS NOT NULL AND band_tx IS NOT NULL GROUP BY dxcc_id, band_tx"
    )
    first_dxcc = {r[0]: r[1] for r in dxcc_rows}
    first_band = {(r[0], r[1]): r[2] for r in band_rows}
    return first_dxcc, first_band


def _qsos_in_range(start_epoch: float, end_epoch: float, limit: int) -> list:
    rows = _execute(
        f"SELECT call, band_tx, band_rx, mode, qso_start, qso_done, grid, dxcc_country, "
        f"qsl_received, rst_sent, rst_received, dxcc_id FROM {_qso_table} "
        f"WHERE qso_start > ? AND qso_start <= ? ORDER BY qso_start DESC LIMIT ?",
        (start_epoch, end_epoch, limit),
    )
    first_dxcc, first_band = _first_worked_times()
    result = []
    for r in rows:
        dxcc_id, band_tx, qso_start = r[11], r[1], r[4]
        result.append({
            "call": r[0], "band_tx": band_tx, "band_rx": r[2], "mode": r[3],
            "qso_start": qso_start, "qso_done": r[5], "grid": r[6], "dxcc_country": r[7],
            "qsl_badge": _qsl_badge(r[8]), "rst_sent": r[9], "rst_received": r[10],
            "is_new_dxcc": dxcc_id is not None and first_dxcc.get(dxcc_id) == qso_start,
            "is_new_band": dxcc_id is not None and band_tx is not None and first_band.get((dxcc_id, band_tx)) == qso_start,
        })
    return result


def recent_qsos(hours: float = 36, limit: int = 200) -> list:
    now = time.time()
    return _qsos_in_range(now - hours * 3600, now, limit)


def qsos_for_month(year: int, month: int, limit: int = 2000) -> list:
    """History browsing: every QSO in one calendar month (UTC), for the
    year/month picker -- as opposed to recent_qsos()'s rolling "last N
    hours" window."""
    start = calendar.timegm((year, month, 1, 0, 0, 0))
    if month == 12:
        end = calendar.timegm((year + 1, 1, 1, 0, 0, 0))
    else:
        end = calendar.timegm((year, month + 1, 1, 0, 0, 0))
    return _qsos_in_range(start - 1, end, limit)  # start-1: BETWEEN-style bounds are exclusive on the low end above


def recent_confirmations(months: float = 3, limit: int = 500) -> list:
    cutoff_date = time.strftime("%Y%m%d", time.gmtime(time.time() - months * 30 * 86400))
    rows = _execute(
        f"SELECT call, band_tx, dxcc_country, mode, qso_start, qsl_received FROM {_qso_table} "
        f"WHERE qsl_received LIKE '%LoTW%' OR qsl_received LIKE '%CardC%'"
    )
    results = []
    for call, band_tx, dxcc_country, mode, qso_start, qsl_received in rows:
        tags = _CONFIRM_TAG_RE.findall(qsl_received or "")
        if not tags:
            continue
        via, confirmed_date = max(tags, key=lambda t: t[1])  # latest date wins
        if confirmed_date < cutoff_date:
            continue
        results.append({
            "call": call, "band_tx": band_tx, "dxcc_country": dxcc_country, "mode": mode,
            "qso_start": qso_start, "confirmed_date": confirmed_date,
            "confirmed_via": "LoTW" if via.upper() == "LOTW" else "Card",
        })
    results.sort(key=lambda r: r["confirmed_date"], reverse=True)
    return results[:limit]


def _applescript_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _run_macloggerdx_command(command: str, arg: str = "", timeout: float = 20.0) -> tuple:
    """Runs a MacLoggerDX AppleScript command taking one text parameter --
    same subprocess/osascript convention as macloggerdx_bridge.send_adif_to_macloggerdx.
    The command returning quickly doesn't necessarily mean the underlying
    LoTW/eQSL fetch is done -- that appears to continue in MacLoggerDX
    itself after the AppleScript call returns (confirmed: the command
    returns near-instantly even though checking LoTW is a real network
    round trip), so a "success" result here means "the request was
    accepted", not "confirmations have already been pulled in"."""
    script = f'tell application "MacLoggerDX" to {command} {_applescript_quote(arg)}'
    try:
        proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "Timed out waiting for MacLoggerDX/osascript"
    except FileNotFoundError:
        return False, "osascript not found -- this only works on macOS"
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "unknown osascript error").strip()
        log.warning("%s failed: %s", command, message)
        return False, message
    return True, (proc.stdout or "").strip()


def trigger_lotw_check() -> tuple:
    return _run_macloggerdx_command("lotwConfirmations")


def trigger_eqsl_check() -> tuple:
    return _run_macloggerdx_command("eqslConfirmations")


# ---------------------------------------------------------------------------
# Flask wiring
# ---------------------------------------------------------------------------

def init_logbook(app, database_path: str, qso_table: str):
    global _database_path, _qso_table
    _database_path = database_path
    _qso_table = qso_table
    app.register_blueprint(logbook_bp)


@logbook_bp.route("/logbook")
def logbook_view():
    return render_template("logbook.html")


@logbook_bp.route("/logbook/recent")
def logbook_recent():
    hours = request.args.get("hours", default=36, type=float)
    try:
        return jsonify(recent_qsos(hours=hours))
    except Exception as exc:
        log.exception("recent_qsos failed")
        return jsonify({"error": str(exc)}), 503


@logbook_bp.route("/logbook/month")
def logbook_month():
    year = request.args.get("year", type=int)
    month = request.args.get("month", type=int)
    if not year or not month or not (1 <= month <= 12):
        return jsonify({"error": "year and month (1-12) are required"}), 400
    try:
        return jsonify(qsos_for_month(year, month))
    except Exception as exc:
        log.exception("qsos_for_month failed")
        return jsonify({"error": str(exc)}), 503


@logbook_bp.route("/logbook/confirmations")
def logbook_confirmations():
    months = request.args.get("months", default=3, type=float)
    try:
        return jsonify(recent_confirmations(months=months))
    except Exception as exc:
        log.exception("recent_confirmations failed")
        return jsonify({"error": str(exc)}), 503


@logbook_bp.route("/logbook/check_lotw", methods=["POST"])
def logbook_check_lotw():
    ok, message = trigger_lotw_check()
    return jsonify({"ok": ok, "message": message or "Requested"})


@logbook_bp.route("/logbook/check_eqsl", methods=["POST"])
def logbook_check_eqsl():
    ok, message = trigger_eqsl_check()
    return jsonify({"ok": ok, "message": message or "Requested"})

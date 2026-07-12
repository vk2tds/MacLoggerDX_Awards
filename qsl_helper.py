#!/usr/bin/env python3
"""
qsl_helper.py -- QSL Helper: finds QSOs that are "at risk" (worked but not
confirmed by LoTW/eQSL/card, for a DXCC entity where we have *no* confirmed
QSO at all) and cross-references each one against WSJT-X's ALL.TXT log to
estimate how likely a confirmation actually is.

ALL.TXT (WSJT-X's plain-text record of every Rx/Tx line) grows forever and
gets large (multi-GB) on an active station, so we don't re-read it on every
page load. Instead a background thread indexes it once into a small local
SQLite cache -- keeping only lines that mention one of our own callsigns --
then just tails newly-appended bytes on subsequent passes.

Also owns qsl_methods.json: a small manually-maintained note per callsign
describing how best to get a QSL from them (direct/bureau/OQRS, typical
cost), unrelated to the ALL.TXT analysis.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import logging
import os
import re
import sqlite3
import threading
import time
from typing import Optional

from flask import Blueprint, jsonify, render_template, request

from ft8_parser import base_callsign, parse_message

log = logging.getLogger("qsl_helper")

CONFIRMED_LIKE = (
    "(qsl_received LIKE '%LoTW%' OR qsl_received LIKE '%eQSL%' "
    "OR qsl_received LIKE '%CardC%' OR qsl_received LIKE '%Card%')"
)

# How far around a logged QSO's timestamp to search ALL.TXT for the actual
# over-the-air exchange. Generous on purpose: MacLoggerDX's qso_start isn't
# always exactly WSJT-X's first or last line for that contact.
MATCH_WINDOW_BEFORE_S = 15 * 60
MATCH_WINDOW_AFTER_S = 30 * 60

# A callsign not seen in lotw-user-activity.csv within this many days is
# treated as "stale" rather than "recently active".
LOTW_RECENT_DAYS = 730


@dataclasses.dataclass
class QslHelperConfig:
    database_path: str
    qso_table: str
    my_calls: tuple = ("VK2TDS",)
    alltxt_path: str = "/Users/darryl/Library/Application Support/WSJT-X/ALL.TXT"
    lotw_activity_file: str = "lotw-user-activity.csv"
    qsl_methods_file: str = "qsl_methods.json"
    cache_db_path: str = "alltxt_cache.sqlite"
    resync_interval_s: float = 60.0


# ---------------------------------------------------------------------------
# ALL.TXT parsing
# ---------------------------------------------------------------------------

_LINE_RE = re.compile(
    r"^(?P<ts>\d{6}_\d{6})\s+(?P<freq>[\d.]+)\s+(?P<rxtx>Rx|Tx)\s+(?P<mode>\S+)\s+"
    r"(?P<snr>-?\d+)\s+(?P<dt>-?[\d.]+)\s+(?P<df>-?\d+)\s+(?P<msg>.+)$"
)


def _parse_ts(ts_str: str) -> Optional[float]:
    # WSJT-X always logs ALL.TXT timestamps in UTC (per its documentation),
    # while qso_start in the MacLoggerDX log is a plain Unix epoch -- so the
    # naive datetime here must be interpreted as UTC, not local time, or
    # every lookup is off by your UTC offset.
    try:
        dt = datetime.datetime.strptime(ts_str, "%y%m%d_%H%M%S").replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def parse_alltxt_line(line: str) -> Optional[dict]:
    """Parse one ALL.TXT line into its fields, or None if it doesn't match
    the standard 'Rx/Tx' decode-line shape (band markers, blank lines,
    WSJT-X restart banners etc. are silently skipped)."""
    m = _LINE_RE.match(line.strip())
    if not m:
        return None
    ts = _parse_ts(m.group("ts"))
    if ts is None:
        return None
    try:
        freq_mhz = float(m.group("freq"))
        snr = int(m.group("snr"))
        dt = float(m.group("dt"))
        df = int(m.group("df"))
    except ValueError:
        return None
    return {
        "ts": ts, "freq_mhz": freq_mhz, "rxtx": m.group("rxtx"), "mode": m.group("mode"),
        "snr": snr, "dt": dt, "df": df, "msg": m.group("msg").strip(),
    }


def _other_call_for(msg: str, my_bases: set) -> Optional[str]:
    """If this decoded message is a direct exchange between us and someone
    else (not a bare CQ, not a hashed/unresolved callsign on our side),
    return the *other* station's base callsign. Otherwise None -- these
    lines aren't indexed since we can never look them up by a specific call.

    Delegates to ft8_parser.parse_message so the "<CALL>" hashed-callsign
    notation (a real, decoded call -- distinct from the literal "<...>"
    unresolved placeholder) is handled the same way everywhere; indexing
    the raw bracketed/unstripped token here previously meant these QSOs
    could never be found again by their plain callsign."""
    parsed = parse_message(msg)
    if parsed.is_cq or not parsed.to_call or not parsed.de_call:
        return None
    to_base = base_callsign(parsed.to_call)
    de_base = base_callsign(parsed.de_call)
    if to_base in my_bases:
        return de_base
    if de_base in my_bases:
        return to_base
    return None


# ---------------------------------------------------------------------------
# Background-indexed ALL.TXT cache
# ---------------------------------------------------------------------------

class AllTxtCache:
    def __init__(self, config: QslHelperConfig):
        self.config = config
        self._my_bases = {base_callsign(c) or c for c in config.my_calls}
        self._lock = threading.Lock()
        # timeout=30: Flask's debug reloader runs this module twice (the
        # "watcher" parent plus the actual serving child), and both end up
        # pointed at the same cache file -- give concurrent writers a chance
        # to wait for the lock rather than raising "database is locked".
        self._db = sqlite3.connect(config.cache_db_path, check_same_thread=False, timeout=30)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS lines ("
            "ts REAL, rxtx TEXT, freq_mhz REAL, mode TEXT, snr INTEGER, dt REAL, df INTEGER, "
            "msg TEXT, other_call TEXT, UNIQUE(ts, rxtx, msg))"
        )
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_lines_other_call ON lines(other_call)")
        self._db.execute("CREATE TABLE IF NOT EXISTS sync_state (path TEXT PRIMARY KEY, offset INTEGER)")
        self._db.commit()
        self._thread: Optional[threading.Thread] = None
        self.status = {"state": "idle", "file_size": 0, "bytes_indexed": 0, "lines_indexed": 0, "error": None,
                        "last_sync": None}

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="alltxt-indexer", daemon=True)
        self._thread.start()

    def _run(self):
        while True:
            try:
                self.sync_once()
            except Exception:
                log.exception("ALL.TXT indexing pass failed")
                self.status["error"] = "Indexing failed -- see server logs"
            time.sleep(self.config.resync_interval_s)

    def sync_once(self):
        path = self.config.alltxt_path
        if not os.path.exists(path):
            self.status["error"] = f"ALL.TXT not found at {path}"
            self.status["state"] = "error"
            return

        file_size = os.path.getsize(path)
        with self._lock:
            row = self._db.execute("SELECT offset FROM sync_state WHERE path=?", (path,)).fetchone()
        offset = row[0] if row else 0

        if offset > file_size:
            # File was rotated/cleared under us -- start over.
            offset = 0
            with self._lock:
                self._db.execute("DELETE FROM lines")
                self._db.commit()

        self.status["state"] = "indexing" if offset == 0 else "updating"
        self.status["file_size"] = file_size

        batch = []
        lines_seen = 0
        lines_since_flush = 0
        with open(path, "r", errors="replace") as f:
            f.seek(offset)
            for raw_line in f:
                if not raw_line.endswith("\n"):
                    break  # partial trailing line -- pick it up next pass
                offset += len(raw_line.encode("utf-8", errors="replace"))
                lines_seen += 1
                lines_since_flush += 1
                parsed = parse_alltxt_line(raw_line)
                if parsed is not None:
                    other = _other_call_for(parsed["msg"], self._my_bases)
                    if other:
                        batch.append((parsed["ts"], parsed["rxtx"], parsed["freq_mhz"], parsed["mode"],
                                      parsed["snr"], parsed["dt"], parsed["df"], parsed["msg"], other))
                # Flush periodically on lines *scanned* (not just matched) so
                # the progress bar moves during a long initial index, where
                # well under 1% of lines match one of our own callsigns.
                if len(batch) >= 5000 or lines_since_flush >= 200_000:
                    self._flush(batch, offset, path)
                    batch = []
                    lines_since_flush = 0

        self._flush(batch, offset, path)
        self.status["state"] = "ready"
        self.status["bytes_indexed"] = offset
        self.status["error"] = None
        self.status["last_sync"] = time.time()
        if lines_seen:
            log.info("ALL.TXT sync: scanned %d new lines up to offset %d/%d", lines_seen, offset, file_size)

    def _flush(self, batch: list, offset: int, path: str):
        with self._lock:
            if batch:
                self._db.executemany(
                    "INSERT OR IGNORE INTO lines (ts, rxtx, freq_mhz, mode, snr, dt, df, msg, other_call) "
                    "VALUES (?,?,?,?,?,?,?,?,?)", batch,
                )
                self.status["lines_indexed"] = self.status.get("lines_indexed", 0) + len(batch)
            self._db.execute(
                "INSERT INTO sync_state (path, offset) VALUES (?, ?) "
                "ON CONFLICT(path) DO UPDATE SET offset=excluded.offset",
                (path, offset),
            )
            self._db.commit()
            self.status["bytes_indexed"] = offset

    def find_exchange(self, other_call: str, near_epoch: Optional[float]) -> list:
        base = base_callsign(other_call) or other_call
        with self._lock:
            if near_epoch:
                rows = self._db.execute(
                    "SELECT ts, rxtx, freq_mhz, mode, snr, dt, df, msg FROM lines "
                    "WHERE other_call = ? AND ts BETWEEN ? AND ? ORDER BY ts",
                    (base, near_epoch - MATCH_WINDOW_BEFORE_S, near_epoch + MATCH_WINDOW_AFTER_S),
                ).fetchall()
            else:
                rows = self._db.execute(
                    "SELECT ts, rxtx, freq_mhz, mode, snr, dt, df, msg FROM lines "
                    "WHERE other_call = ? ORDER BY ts", (base,),
                ).fetchall()
        return rows


# ---------------------------------------------------------------------------
# LoTW user-activity lookup
# ---------------------------------------------------------------------------

class LotwActivity:
    """Last-known LoTW activity date per callsign, from the ARRL-published
    lotw-user-activity.csv snapshot (call,date,time -- one row per user)."""

    def __init__(self, path: str):
        self.path = path
        self._by_call: dict = {}
        self._load()

    def _load(self):
        try:
            with open(self.path, "r", errors="replace") as f:
                for line in f:
                    parts = line.strip().split(",")
                    if len(parts) < 2:
                        continue
                    call, date = parts[0], parts[1]
                    self._by_call[call] = date
            log.info("Loaded %d LoTW user-activity records from %s", len(self._by_call), self.path)
        except OSError:
            log.exception("Could not read LoTW user-activity file %s", self.path)

    def last_active(self, call: str) -> Optional[str]:
        base = base_callsign(call) or call
        return self._by_call.get(base) or self._by_call.get(call)

    def is_recent(self, call: str) -> Optional[bool]:
        date_str = self.last_active(call)
        if not date_str:
            return None
        try:
            d = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return None
        return (datetime.datetime.now() - d).days <= LOTW_RECENT_DAYS


# ---------------------------------------------------------------------------
# Likelihood scoring
# ---------------------------------------------------------------------------

def analyze_exchange(rows: list, my_bases: set, lotw: LotwActivity, other_call: str) -> dict:
    lines = []
    two_way_confirmed = False
    reached_final = False
    saw_rrr_only = False
    rx_snrs = []

    for ts, rxtx, freq_mhz, mode, snr, dt, df, msg in rows:
        parsed = parse_message(msg)
        if rxtx == "Rx" and parsed.to_call and base_callsign(parsed.to_call) in my_bases:
            two_way_confirmed = True
            if snr is not None:
                rx_snrs.append(snr)
        if parsed.is_rr73 or parsed.is_73:
            reached_final = True
        elif parsed.is_rrr:
            saw_rrr_only = True
        lines.append({
            "ts": ts, "time": datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
            "rxtx": rxtx, "freq_mhz": freq_mhz, "mode": mode, "snr": snr, "msg": msg,
        })

    avg_snr = round(sum(rx_snrs) / len(rx_snrs), 1) if rx_snrs else None
    lotw_last = lotw.last_active(other_call)
    lotw_recent = lotw.is_recent(other_call)

    if not rows:
        likelihood, reason = "unknown", "No matching exchange found in ALL.TXT for this QSO (predates ALL.TXT, not a WSJT-X mode, or made elsewhere)."
    elif lotw_last is None:
        likelihood = "low"
        reason = "This callsign has never appeared in LoTW's user-activity list -- unlikely to ever confirm via LoTW, regardless of QSO quality."
    elif not two_way_confirmed:
        likelihood, reason = "low", "ALL.TXT shows no reply from them addressed to your callsign -- this may have been logged from a one-sided decode."
    elif reached_final and lotw_recent:
        likelihood, reason = "high", f"Exchange reached RR73/73 both ways, and this callsign uploaded to LoTW as recently as {lotw_last}."
    elif reached_final and not lotw_recent:
        likelihood, reason = "medium", f"Exchange reached RR73/73, but this callsign's LoTW activity looks stale (last seen {lotw_last})."
    elif not reached_final and lotw_recent:
        likelihood, reason = "medium", f"Two-way reply seen but the exchange didn't clearly reach RR73/73; callsign uploaded to LoTW as recently as {lotw_last}."
    else:
        likelihood, reason = "low", f"Exchange didn't reach RR73/73 and this callsign's LoTW activity looks stale (last seen {lotw_last})."

    return {
        "exchange_count": len(rows),
        "two_way_confirmed": two_way_confirmed,
        "reached_rr73_or_73": reached_final,
        "saw_rrr_only": saw_rrr_only and not reached_final,
        "avg_snr_rx": avg_snr,
        "lotw_last_active": lotw_last,
        "lotw_recent": lotw_recent,
        "likelihood": likelihood,
        "likelihood_reason": reason,
        "lines": lines,
    }


# ---------------------------------------------------------------------------
# At-risk QSO lookup (MacLoggerDX log, read-only)
# ---------------------------------------------------------------------------

def _connect_ro(database_path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{database_path}?mode=ro", uri=True, timeout=5.0)

def find_at_risk_qsos(database_path: str, qso_table: str) -> list:
    """(DXCC entity, band) combinations with zero LoTW/eQSL/card confirmation
    -- e.g. Northern Ireland worked and confirmed on 20M but not on 12M/10M
    still flags the 12M/10M QSOs -- and every QSO on record for each such
    combination."""
    conn = _connect_ro(database_path)
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT dxcc_country, band_tx FROM {qso_table} "
            f"WHERE dxcc_country IS NOT NULL AND band_tx IS NOT NULL AND call NOT LIKE '%/MM' "
            f"GROUP BY dxcc_country, band_tx HAVING SUM(CASE WHEN {CONFIRMED_LIKE} THEN 1 ELSE 0 END) = 0"
        )
        pairs = cur.fetchall()
        if not pairs:
            return []
        clauses = " OR ".join(["(dxcc_country = ? AND band_tx = ?)"] * len(pairs))
        params = [v for pair in pairs for v in pair]
        cur.execute(
            f"SELECT call, my_call, dxcc_country, dxcc_id, band_tx, band_rx, mode, qso_start, qso_done, qsl_received "
            f"FROM {qso_table} WHERE {clauses} ORDER BY dxcc_country, band_tx, qso_start",
            params,
        )
        cols = ["call", "my_call", "dxcc_country", "dxcc_id", "band_tx", "band_rx", "mode", "qso_start", "qso_done", "qsl_received"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# QSL "how to work them" notes (manually maintained JSON)
# ---------------------------------------------------------------------------

class QslMethods:
    def __init__(self, path: str):
        self.path = path
        # Reentrant: upsert()/delete() call _load_locked() while already
        # holding this lock.
        self._lock = threading.RLock()

    def _load_locked(self) -> list:
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, "r") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            log.exception("Could not read %s", self.path)
            return []

    def load(self) -> list:
        with self._lock:
            return self._load_locked()

    def _save(self, entries: list):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(entries, f, indent=2)
        os.replace(tmp, self.path)

    def upsert(self, call: str, method: str, cost: str, notes: str) -> list:
        call = call.strip().upper()
        with self._lock:
            entries = self._load_locked()
            for e in entries:
                if e.get("call") == call:
                    e["method"], e["cost"], e["notes"] = method, cost, notes
                    e["updated"] = datetime.datetime.now().isoformat(timespec="seconds")
                    break
            else:
                entries.append({
                    "call": call, "method": method, "cost": cost, "notes": notes,
                    "updated": datetime.datetime.now().isoformat(timespec="seconds"),
                })
            self._save(entries)
            return entries

    def delete(self, call: str) -> list:
        call = call.strip().upper()
        with self._lock:
            entries = [e for e in self._load_locked() if e.get("call") != call]
            self._save(entries)
            return entries


# ---------------------------------------------------------------------------
# Flask wiring
# ---------------------------------------------------------------------------

qsl_bp = Blueprint("qsl", __name__, template_folder="templates")

_cache: Optional[AllTxtCache] = None
_lotw: Optional[LotwActivity] = None
_methods: Optional[QslMethods] = None
_config: Optional[QslHelperConfig] = None


def init_qsl_helper(app, config: QslHelperConfig):
    """Create the ALL.TXT cache (and start its background indexer), load the
    LoTW activity table, and register the /qsl routes. Call once at startup."""
    global _cache, _lotw, _methods, _config
    _config = config
    _cache = AllTxtCache(config)
    _cache.start()
    _lotw = LotwActivity(config.lotw_activity_file)
    _methods = QslMethods(config.qsl_methods_file)
    app.register_blueprint(qsl_bp)
    return _cache


@qsl_bp.route("/qsl")
def qsl_view():
    return render_template("qsl_helper.html", my_calls=", ".join(_config.my_calls) if _config else "")


@qsl_bp.route("/qsl/data")
def qsl_data():
    if _config is None or _cache is None:
        return jsonify({"error": "QSL Helper not initialised"}), 503

    my_bases = {base_callsign(c) or c for c in _config.my_calls}
    methods_by_call = {e["call"]: e for e in _methods.load()}

    entities = {}
    for qso in find_at_risk_qsos(_config.database_path, _config.qso_table):
        rows = _cache.find_exchange(qso["call"], qso.get("qso_start"))
        analysis = analyze_exchange(rows, my_bases, _lotw, qso["call"])
        entry = {
            "call": qso["call"],
            "my_call": qso["my_call"],
            "dxcc_country": qso["dxcc_country"],
            "band": qso["band_tx"] or qso["band_rx"],
            "mode": qso["mode"],
            "qso_start": qso["qso_start"],
            "qso_start_str": (
                datetime.datetime.fromtimestamp(qso["qso_start"]).strftime("%Y-%m-%d %H:%M")
                if qso["qso_start"] else None
            ),
            "qsl_received": qso["qsl_received"],
            "qsl_method": methods_by_call.get(qso["call"]),
            **analysis,
        }
        group_key = f"{qso['dxcc_country']} — {qso['band_tx']}"
        entities.setdefault(group_key, []).append(entry)

    return jsonify({
        "entities": entities,
        "cache_status": _cache.status,
        "methods": _methods.load(),
    })


@qsl_bp.route("/qsl/reindex", methods=["POST"])
def qsl_reindex():
    if _cache is None:
        return jsonify({"error": "QSL Helper not initialised"}), 503
    try:
        _cache.sync_once()
    except Exception:
        log.exception("Manual ALL.TXT resync failed")
    return jsonify(_cache.status)


@qsl_bp.route("/qsl/methods", methods=["POST"])
def qsl_methods_upsert():
    if _methods is None:
        return jsonify({"error": "QSL Helper not initialised"}), 503
    body = request.get_json(silent=True) or {}
    call = (body.get("call") or "").strip()
    if not call:
        return jsonify({"error": "call is required"}), 400
    entries = _methods.upsert(
        call=call,
        method=body.get("method", ""),
        cost=body.get("cost", ""),
        notes=body.get("notes", ""),
    )
    return jsonify({"methods": entries})


@qsl_bp.route("/qsl/methods/delete", methods=["POST"])
def qsl_methods_delete():
    if _methods is None:
        return jsonify({"error": "QSL Helper not initialised"}), 503
    body = request.get_json(silent=True) or {}
    call = (body.get("call") or "").strip()
    if not call:
        return jsonify({"error": "call is required"}), 400
    entries = _methods.delete(call)
    return jsonify({"methods": entries})

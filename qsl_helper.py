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
import shutil
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from typing import Optional

from flask import Blueprint, jsonify, render_template, request

from dxcc_lookup import DxccResolver
from ft8_parser import base_callsign, parse_message

log = logging.getLogger("qsl_helper")

# How far around a logged QSO's timestamp to search ALL.TXT for the actual
# over-the-air exchange. Generous on purpose: MacLoggerDX's qso_start isn't
# always exactly WSJT-X's first or last line for that contact.
MATCH_WINDOW_BEFORE_S = 15 * 60
MATCH_WINDOW_AFTER_S = 30 * 60

# A callsign not seen in lotw-user-activity.csv within this many days is
# treated as "stale" rather than "recently active".
LOTW_RECENT_DAYS = 730

# ARRL's official published snapshot -- one row per LoTW user, refreshed daily.
LOTW_ACTIVITY_URL = "https://lotw.arrl.org/lotw-user-activity.csv"


@dataclasses.dataclass
class QslHelperConfig:
    database_path: str
    qso_table: str
    dxcc_file: str = "dxcc.txt"
    my_calls: tuple = ("VK2TDS",)
    alltxt_path: str = "/Users/darryl/Library/Application Support/WSJT-X/ALL.TXT"
    lotw_activity_file: str = "lotw-user-activity.csv"
    qsl_methods_file: str = "qsl_methods.json"
    not_in_log_file: str = "qsl_not_in_log.json"
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
            "msg TEXT, other_call TEXT, raw TEXT, UNIQUE(ts, rxtx, msg))"
        )
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_lines_other_call ON lines(other_call)")
        self._db.execute("CREATE TABLE IF NOT EXISTS sync_state (path TEXT PRIMARY KEY, offset INTEGER)")
        # Migration: older caches predate the 'raw' column (added so exchange
        # lines can be displayed verbatim, unchanged from ALL.TXT, rather than
        # reconstructed from parsed fields). If it's missing, add it and force
        # a full re-index so every row gets backfilled -- correctness over
        # avoiding the one-time re-scan cost.
        cols = {row[1] for row in self._db.execute("PRAGMA table_info(lines)").fetchall()}
        if "raw" not in cols:
            self._db.execute("ALTER TABLE lines ADD COLUMN raw TEXT")
            self._db.execute("DELETE FROM lines")
            self._db.execute("DELETE FROM sync_state")
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
                                      parsed["snr"], parsed["dt"], parsed["df"], parsed["msg"], other,
                                      raw_line.rstrip("\r\n")))
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
                    "INSERT OR IGNORE INTO lines (ts, rxtx, freq_mhz, mode, snr, dt, df, msg, other_call, raw) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)", batch,
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
                    "SELECT ts, rxtx, freq_mhz, mode, snr, dt, df, msg, raw FROM lines "
                    "WHERE other_call = ? AND ts BETWEEN ? AND ? ORDER BY ts",
                    (base, near_epoch - MATCH_WINDOW_BEFORE_S, near_epoch + MATCH_WINDOW_AFTER_S),
                ).fetchall()
            else:
                rows = self._db.execute(
                    "SELECT ts, rxtx, freq_mhz, mode, snr, dt, df, msg, raw FROM lines "
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

    def reload(self):
        self._by_call = {}
        self._load()

    @property
    def count(self) -> int:
        return len(self._by_call)

    @property
    def updated(self) -> Optional[float]:
        try:
            return os.path.getmtime(self.path)
        except OSError:
            return None

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
        return (datetime.datetime.utcnow() - d).days <= LOTW_RECENT_DAYS


def update_lotw_activity(path: str, url: str = LOTW_ACTIVITY_URL, timeout: float = 30.0) -> tuple:
    """Download ARRL's current lotw-user-activity.csv snapshot and atomically
    replace `path`. Returns (ok, message)."""
    tmp = path + ".tmp"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MacLoggerDX-Awards/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as f:
            shutil.copyfileobj(resp, f)
        os.replace(tmp, path)
    except (OSError, urllib.error.URLError) as exc:
        if os.path.exists(tmp):
            os.remove(tmp)
        log.exception("Failed to download LoTW user-activity file from %s", url)
        return False, str(exc)
    return True, "ok"


# ---------------------------------------------------------------------------
# Likelihood scoring
# ---------------------------------------------------------------------------

def analyze_exchange(rows: list, my_bases: set, lotw: LotwActivity, other_call: str) -> dict:
    lines = []
    two_way_confirmed = False
    reached_final = False
    saw_rrr_only = False
    rx_snrs = []

    for ts, rxtx, freq_mhz, mode, snr, dt, df, msg, raw in rows:
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
            "ts": ts, "time": datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
            "rxtx": rxtx, "freq_mhz": freq_mhz, "mode": mode, "snr": snr, "msg": msg, "raw": raw,
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

# Local VK2-to-VK2 2M contacts are same-entity VHF ragchews -- they don't
# advance any DXCC chase (you can't "need" your own country) and just add
# noise to the at-risk list, so they're excluded here. See NOT_LOCAL_2M_VK2
# footnote surfaced in the UI.
NOT_LOCAL_2M_VK2 = "NOT (band_tx = '2M' AND call LIKE 'VK2%' AND my_call LIKE 'VK2%')"


def _is_confirmed(qsl_received) -> bool:
    if not qsl_received:
        return False
    return any(tag in qsl_received for tag in ("LoTW", "eQSL", "CardC", "Card"))


def find_at_risk_qsos(database_path: str, qso_table: str, dxcc_resolver: Optional[DxccResolver] = None) -> list:
    """(DXCC entity, band) combinations with zero LoTW/eQSL/card confirmation
    -- e.g. Northern Ireland worked and confirmed on 20M but not on 12M/10M
    still flags the 12M/10M QSOs -- and every QSO on record for each such
    combination. Excludes Maritime Mobile and local VK2-to-VK2 2M contacts.

    Grouping is keyed on the DXCC entity resolved fresh from each QSO's
    callsign (via dxcc_resolver), not the dxcc_country/dxcc_id text stored in
    MacLoggerDX's own log -- that log has been seen to store the same entity
    under multiple spellings ("United States" vs "United States of America")
    and occasionally a wrong id (e.g. a Hawaii QSO tagged with the mainland
    US id), which would otherwise split or merge groups incorrectly. Falls
    back to the stored fields only when the resolver can't place the call."""
    conn = _connect_ro(database_path)
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT call, my_call, dxcc_country, dxcc_id, band_tx, band_rx, mode, qso_start, qso_done, qsl_received "
            f"FROM {qso_table} "
            f"WHERE dxcc_country IS NOT NULL AND band_tx IS NOT NULL AND call NOT LIKE '%/MM' "
            f"AND {NOT_LOCAL_2M_VK2}"
        )
        cols = ["call", "my_call", "dxcc_country", "dxcc_id", "band_tx", "band_rx", "mode", "qso_start", "qso_done", "qsl_received"]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()

    for row in rows:
        entity = dxcc_resolver.lookup(row["call"]) if dxcc_resolver else None
        if entity is not None:
            row["entity_id"] = entity.dxcc_id
            row["entity_name"] = entity.name
        else:
            row["entity_id"] = row["dxcc_id"]
            row["entity_name"] = row["dxcc_country"]

    groups: dict = {}
    for row in rows:
        groups.setdefault((row["entity_id"], row["band_tx"]), []).append(row)

    at_risk = []
    for group_rows in groups.values():
        if any(_is_confirmed(r["qsl_received"]) for r in group_rows):
            continue
        at_risk.extend(group_rows)

    at_risk.sort(key=lambda r: (r["entity_name"] or "", r["band_tx"] or "", r["qso_start"] or 0))
    return at_risk


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
                    # Preserve status (pending/done) across edits -- editing
                    # the method/cost/notes on a call you've already marked
                    # done shouldn't silently reopen it.
                    e["method"], e["cost"], e["notes"] = method, cost, notes
                    e.setdefault("status", "pending")
                    e["updated"] = datetime.datetime.utcnow().isoformat(timespec="seconds")
                    break
            else:
                entries.append({
                    "call": call, "method": method, "cost": cost, "notes": notes,
                    "status": "pending",
                    "updated": datetime.datetime.utcnow().isoformat(timespec="seconds"),
                })
            self._save(entries)
            return entries

    def set_status(self, call: str, status: str) -> list:
        call = call.strip().upper()
        with self._lock:
            entries = self._load_locked()
            for e in entries:
                if e.get("call") == call:
                    e["status"] = status
                    e["updated"] = datetime.datetime.utcnow().isoformat(timespec="seconds")
                    break
            self._save(entries)
            return entries

    def delete(self, call: str) -> list:
        call = call.strip().upper()
        with self._lock:
            entries = [e for e in self._load_locked() if e.get("call") != call]
            self._save(entries)
            return entries


def not_in_log_key(call: str, band: str, mode: str, qso_start) -> str:
    """A QSO's (call, band, mode, qso_start) is unique enough to identify one
    specific logged contact -- used both to mark a QSO 'not in their log' and
    to filter it back out of the at-risk list on future loads."""
    return f"{(call or '').strip().upper()}|{band or ''}|{mode or ''}|{qso_start or ''}"


class NotInLogList:
    """QSOs the operator has flagged as 'not in the other side's log' --
    hidden from the at-risk table and shown instead as a one-line list at the
    bottom of the page, with an undo. Persisted so the flag survives reloads
    (the at-risk list itself is recomputed from the live log every time)."""

    def __init__(self, path: str):
        self.path = path
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

    def keys(self) -> set:
        return {e["key"] for e in self.load()}

    def mark(self, entry: dict) -> list:
        with self._lock:
            entries = self._load_locked()
            if not any(e["key"] == entry["key"] for e in entries):
                entry = dict(entry)
                entry["marked"] = datetime.datetime.utcnow().isoformat(timespec="seconds")
                entries.append(entry)
                self._save(entries)
            return entries

    def unmark(self, key: str) -> list:
        with self._lock:
            entries = [e for e in self._load_locked() if e.get("key") != key]
            self._save(entries)
            return entries


# ---------------------------------------------------------------------------
# Flask wiring
# ---------------------------------------------------------------------------

qsl_bp = Blueprint("qsl", __name__, template_folder="templates")

_cache: Optional[AllTxtCache] = None
_lotw: Optional[LotwActivity] = None
_methods: Optional[QslMethods] = None
_not_in_log: Optional[NotInLogList] = None
_dxcc_resolver: Optional[DxccResolver] = None
_config: Optional[QslHelperConfig] = None


def get_cache() -> Optional[AllTxtCache]:
    """Accessor for other blueprints (e.g. the callsign-history lookup in
    live_monitor.py) that want to reuse the shared ALL.TXT cache rather than
    indexing it a second time."""
    return _cache


def init_qsl_helper(app, config: QslHelperConfig):
    """Create the ALL.TXT cache (and start its background indexer), load the
    LoTW activity table and DXCC resolver, and register the /qsl routes. Call
    once at startup."""
    global _cache, _lotw, _methods, _not_in_log, _dxcc_resolver, _config
    _config = config
    _cache = AllTxtCache(config)
    _cache.start()
    _lotw = LotwActivity(config.lotw_activity_file)
    _methods = QslMethods(config.qsl_methods_file)
    _not_in_log = NotInLogList(config.not_in_log_file)
    _dxcc_resolver = DxccResolver(config.dxcc_file)
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
    hidden_keys = _not_in_log.keys()

    entities = {}
    for qso in find_at_risk_qsos(_config.database_path, _config.qso_table, _dxcc_resolver):
        key = not_in_log_key(qso["call"], qso["band_tx"], qso["mode"], qso["qso_start"])
        if key in hidden_keys:
            continue
        rows = _cache.find_exchange(qso["call"], qso.get("qso_start"))
        analysis = analyze_exchange(rows, my_bases, _lotw, qso["call"])
        entry = {
            "key": key,
            "call": qso["call"],
            "my_call": qso["my_call"],
            "dxcc_country": qso["entity_name"],
            "band": qso["band_tx"] or qso["band_rx"],
            "mode": qso["mode"],
            "qso_start": qso["qso_start"],
            "qso_start_str": (
                datetime.datetime.utcfromtimestamp(qso["qso_start"]).strftime("%Y-%m-%d %H:%M")
                if qso["qso_start"] else None
            ),
            "qsl_received": qso["qsl_received"],
            "qsl_method": methods_by_call.get(qso["call"]),
            **analysis,
        }
        group_key = f"{qso['entity_name']} — {qso['band_tx']}"
        entities.setdefault(group_key, []).append(entry)

    return jsonify({
        "entities": entities,
        "cache_status": _cache.status,
        "methods": _methods.load(),
        "not_in_log": _not_in_log.load(),
        "lotw_status": {"count": _lotw.count, "updated": _lotw.updated},
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


@qsl_bp.route("/qsl/methods/status", methods=["POST"])
def qsl_methods_status():
    if _methods is None:
        return jsonify({"error": "QSL Helper not initialised"}), 503
    body = request.get_json(silent=True) or {}
    call = (body.get("call") or "").strip()
    status = (body.get("status") or "").strip()
    if not call or status not in ("pending", "done"):
        return jsonify({"error": "call and a valid status (pending/done) are required"}), 400
    entries = _methods.set_status(call, status)
    return jsonify({"methods": entries})


@qsl_bp.route("/qsl/lotw/update", methods=["POST"])
def qsl_lotw_update():
    if _lotw is None or _config is None:
        return jsonify({"error": "QSL Helper not initialised"}), 503
    ok, message = update_lotw_activity(_config.lotw_activity_file)
    if ok:
        _lotw.reload()
    return jsonify({"ok": ok, "message": message, "lotw_status": {"count": _lotw.count, "updated": _lotw.updated}})


@qsl_bp.route("/qsl/not_in_log", methods=["POST"])
def qsl_not_in_log_mark():
    if _not_in_log is None:
        return jsonify({"error": "QSL Helper not initialised"}), 503
    body = request.get_json(silent=True) or {}
    call = (body.get("call") or "").strip().upper()
    band = (body.get("band") or "").strip()
    mode = (body.get("mode") or "").strip()
    qso_start = body.get("qso_start")
    if not call:
        return jsonify({"error": "call is required"}), 400
    key = not_in_log_key(call, band, mode, qso_start)
    entry = {
        "key": key,
        "call": call,
        "band": band,
        "mode": mode,
        "qso_start": qso_start,
        "dxcc_country": body.get("dxcc_country") or "",
        "qso_start_str": body.get("qso_start_str") or "",
    }
    entries = _not_in_log.mark(entry)
    return jsonify({"not_in_log": entries})


@qsl_bp.route("/qsl/not_in_log/undo", methods=["POST"])
def qsl_not_in_log_undo():
    if _not_in_log is None:
        return jsonify({"error": "QSL Helper not initialised"}), 503
    body = request.get_json(silent=True) or {}
    key = body.get("key") or ""
    if not key:
        return jsonify({"error": "key is required"}), 400
    entries = _not_in_log.unmark(key)
    return jsonify({"not_in_log": entries})

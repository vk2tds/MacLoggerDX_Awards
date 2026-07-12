#!/usr/bin/env python3
"""
log_status.py -- Read-only, live lookups against the MacLoggerDX SQLite log
(the same database + table macloggerdx_awards.analysis already points at:
`database_name` / `qso_table`, e.g. "qso_table_v008") to answer, for a
callsign we've just heard on the air:

    - have we worked this call before (ever / on this band / on this mode)?
    - is it confirmed (LoTW / eQSL / card)?
    - is its DXCC / CQ zone / grid-square new to us?

Opens the database read-only (SQLite URI "mode=ro") so we never risk
corrupting MacLoggerDX's live log, and never block it -- SQLite allows
concurrent readers alongside a writer; a query that lands mid-write simply
gets retried with a short backoff.

Column availability is introspected at startup (PRAGMA table_info) so this
degrades gracefully if your qso_table schema differs slightly from the
v008 layout macloggerdx_awards.py was written against (e.g. no `state` or
`iota` column) -- checks that need a missing column are just skipped.
"""

from __future__ import annotations

import collections
import dataclasses
import logging
import sqlite3
import time
from typing import Optional

log = logging.getLogger("log_status")

# Same QSL-received matching convention as macloggerdx_awards.analysis.conditions.
CONFIRMED_LIKE = "(qsl_received LIKE '%LoTW%' OR qsl_received LIKE '%eQSL%' OR qsl_received LIKE '%CardC%' OR qsl_received LIKE '%Card%')"


def _is_lotw(qsl_received: Optional[str]) -> bool:
    """Strict LoTW-only confirmation check, for the Live Monitor's
    green/orange/red colouring (as distinct from CONFIRMED_LIKE, which the
    rest of the app treats as LoTW/eQSL/card all being equally 'confirmed')."""
    return bool(qsl_received) and "LOTW" in qsl_received.upper()


def _empty_scoped_index() -> dict:
    return {
        "worked": {"overall": set(), "band": collections.defaultdict(set),
                   "mode": collections.defaultdict(set), "band_mode": collections.defaultdict(set)},
        "confirmed": {"overall": set(), "band": collections.defaultdict(set),
                      "mode": collections.defaultdict(set), "band_mode": collections.defaultdict(set)},
    }


def _build_scoped_index(rows) -> dict:
    """rows: iterable of (key, band, mode, qsl_received) covering every QSO
    for some attribute (DXCC id, 4-char grid, ...). Classifies each row into
    the overall/band/mode/band+mode 'worked' and (LoTW-)'confirmed' buckets
    it belongs to, so a single bulk query can answer all four scope
    combinations without re-querying the database on checkbox toggle."""
    idx = _empty_scoped_index()
    for key, band, mode, qsl_received in rows:
        if key is None:
            continue
        confirmed = _is_lotw(qsl_received)
        idx["worked"]["overall"].add(key)
        if confirmed:
            idx["confirmed"]["overall"].add(key)
        if band:
            idx["worked"]["band"][band].add(key)
            if confirmed:
                idx["confirmed"]["band"][band].add(key)
        if mode:
            idx["worked"]["mode"][mode].add(key)
            if confirmed:
                idx["confirmed"]["mode"][mode].add(key)
        if band and mode:
            idx["worked"]["band_mode"][(band, mode)].add(key)
            if confirmed:
                idx["confirmed"]["band_mode"][(band, mode)].add(key)
    return idx


def _scoped_status(idx: dict, key, band: Optional[str], mode: Optional[str], use_band: bool, use_mode: bool) -> str:
    """One of 'confirmed' / 'worked' / 'none' / 'unknown' -- 'unknown' when
    the requested scope needs a band or mode we don't have for this decode."""
    if key is None:
        return "unknown"
    if use_band and use_mode:
        bucket, sub = ("band_mode", (band, mode)) if (band and mode) else (None, None)
    elif use_band:
        bucket, sub = ("band", band) if band else (None, None)
    elif use_mode:
        bucket, sub = ("mode", mode) if mode else (None, None)
    else:
        bucket, sub = "overall", None
    if bucket is None:
        return "unknown"
    confirmed_set = idx["confirmed"]["overall"] if bucket == "overall" else idx["confirmed"][bucket][sub]
    worked_set = idx["worked"]["overall"] if bucket == "overall" else idx["worked"][bucket][sub]
    if key in confirmed_set:
        return "confirmed"
    if key in worked_set:
        return "worked"
    return "none"


@dataclasses.dataclass
class CallStatus:
    callsign: str
    worked_before: bool = False
    worked_this_band: bool = False
    worked_this_mode: bool = False
    worked_this_band_and_mode: bool = False
    confirmed_ever: bool = False
    confirmed_this_band: bool = False
    confirmed_lotw_ever: bool = False
    confirmed_lotw_this_band: bool = False
    confirmed_lotw_this_mode: bool = False
    confirmed_lotw_band_and_mode: bool = False
    qso_count: int = 0
    last_worked: Optional[str] = None
    dxcc_country: Optional[str] = None
    dxcc_id: Optional[int] = None
    cq_zone: Optional[str] = None
    grids_worked: Optional[list] = None
    error: Optional[str] = None

    def status_for_scope(self, use_band: bool, use_mode: bool) -> str:
        """One of 'confirmed' / 'worked' / 'none', for the given band/mode
        scope -- used to colour the Call cell in the Live Monitor table."""
        if use_band and use_mode:
            worked, confirmed = self.worked_this_band_and_mode, self.confirmed_lotw_band_and_mode
        elif use_band:
            worked, confirmed = self.worked_this_band, self.confirmed_lotw_this_band
        elif use_mode:
            worked, confirmed = self.worked_this_mode, self.confirmed_lotw_this_mode
        else:
            worked, confirmed = self.worked_before, self.confirmed_lotw_ever
        if confirmed:
            return "confirmed"
        if worked:
            return "worked"
        return "none"

    def status_all_scopes(self) -> dict:
        return {
            "overall": self.status_for_scope(False, False),
            "band": self.status_for_scope(True, False),
            "mode": self.status_for_scope(False, True),
            "band_mode": self.status_for_scope(True, True),
        }


class LogStatusChecker:
    def __init__(self, database_path: str, qso_table: str, retry_attempts: int = 3, retry_delay_s: float = 0.15):
        self.database_path = database_path
        self.qso_table = qso_table
        self.retry_attempts = retry_attempts
        self.retry_delay_s = retry_delay_s
        self._columns: set = set()
        self._refresh_columns()

        # Caches, rebuilt on demand (see refresh_worked_sets) so the hot
        # per-decode path never has to hit the DB with an expensive
        # aggregate query.
        self.worked_dxcc_ids: set = set()
        self.worked_cq_zones: set = set()
        self.worked_grids4: set = set()
        self.worked_calls: set = set()
        self.last_refresh: Optional[float] = None

        # Band/mode-scoped worked + LoTW-confirmed sets, for the Live
        # Monitor's per-band/per-mode colour-coding toggle.
        self._dxcc_scoped: dict = _empty_scoped_index()
        self._grid4_scoped: dict = _empty_scoped_index()

    # -- connection handling -------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        uri = f"file:{self.database_path}?mode=ro"
        return sqlite3.connect(uri, uri=True, timeout=5.0)

    def _execute(self, sql: str, params: tuple = ()):
        last_exc = None
        for attempt in range(self.retry_attempts):
            try:
                conn = self._connect()
                try:
                    cur = conn.cursor()
                    cur.execute(sql, params)
                    return cur.fetchall()
                finally:
                    conn.close()
            except sqlite3.OperationalError as exc:
                last_exc = exc
                time.sleep(self.retry_delay_s * (attempt + 1))
        raise last_exc

    def _refresh_columns(self):
        try:
            rows = self._execute(f"PRAGMA table_info({self.qso_table})")
            self._columns = {r[1] for r in rows}
            log.info("qso_table columns detected: %s", sorted(self._columns))
        except Exception:
            log.exception("Could not read schema for %s -- is the database path correct?", self.qso_table)
            self._columns = set()

    def has_column(self, name: str) -> bool:
        return name in self._columns

    # -- bulk caches, used for the "is this a brand-new DXCC/zone/grid" flags --

    def refresh_worked_sets(self):
        """Rebuild the in-memory 'have I ever worked X' sets. Call this
        occasionally (e.g. every N minutes, or after a manual refresh
        button) rather than on every single decode."""
        if not self._columns:
            self._refresh_columns()
        t0 = time.time()
        try:
            if self.has_column("dxcc_id"):
                rows = self._execute(f"SELECT DISTINCT dxcc_id FROM {self.qso_table} WHERE dxcc_id IS NOT NULL")
                self.worked_dxcc_ids = {r[0] for r in rows}
            if self.has_column("cq_zone"):
                rows = self._execute(f"SELECT DISTINCT cq_zone FROM {self.qso_table} WHERE cq_zone IS NOT NULL")
                self.worked_cq_zones = {str(r[0]).lstrip("0") or "0" for r in rows}
            if self.has_column("grid"):
                rows = self._execute(f"SELECT DISTINCT substr(grid,1,4) FROM {self.qso_table} WHERE grid IS NOT NULL AND length(grid) >= 4")
                self.worked_grids4 = {r[0].upper() for r in rows if r[0]}
            if self.has_column("call"):
                rows = self._execute(f"SELECT DISTINCT call FROM {self.qso_table} WHERE call IS NOT NULL")
                self.worked_calls = {r[0].upper() for r in rows if r[0]}

            band_col = "band_rx" if self.has_column("band_rx") else "NULL"
            mode_col = "mode" if self.has_column("mode") else "NULL"
            qsl_col = "qsl_received" if self.has_column("qsl_received") else "NULL"

            if self.has_column("dxcc_id"):
                rows = self._execute(
                    f"SELECT dxcc_id, {band_col}, {mode_col}, {qsl_col} FROM {self.qso_table} WHERE dxcc_id IS NOT NULL"
                )
                self._dxcc_scoped = _build_scoped_index(rows)
            if self.has_column("grid"):
                rows = self._execute(
                    f"SELECT substr(grid,1,4), {band_col}, {mode_col}, {qsl_col} FROM {self.qso_table} "
                    f"WHERE grid IS NOT NULL AND length(grid) >= 4"
                )
                rows = [(g.upper() if g else None, b, m, q) for g, b, m, q in rows]
                self._grid4_scoped = _build_scoped_index(rows)

            self.last_refresh = time.time()
            log.info("Refreshed worked-before caches in %.2fs (%d DXCC, %d zones, %d grids, %d calls)",
                      time.time() - t0, len(self.worked_dxcc_ids), len(self.worked_cq_zones),
                      len(self.worked_grids4), len(self.worked_calls))
        except Exception:
            log.exception("Failed to refresh worked-before caches")

    def entity_status_all_scopes(self, dxcc_id: Optional[int], band: Optional[str], mode: Optional[str]) -> dict:
        return {
            "overall": _scoped_status(self._dxcc_scoped, dxcc_id, band, mode, False, False),
            "band": _scoped_status(self._dxcc_scoped, dxcc_id, band, mode, True, False),
            "mode": _scoped_status(self._dxcc_scoped, dxcc_id, band, mode, False, True),
            "band_mode": _scoped_status(self._dxcc_scoped, dxcc_id, band, mode, True, True),
        }

    def grid_status_all_scopes(self, grid: Optional[str], band: Optional[str], mode: Optional[str]) -> dict:
        key = grid[:4].upper() if grid and len(grid) >= 4 else None
        return {
            "overall": _scoped_status(self._grid4_scoped, key, band, mode, False, False),
            "band": _scoped_status(self._grid4_scoped, key, band, mode, True, False),
            "mode": _scoped_status(self._grid4_scoped, key, band, mode, False, True),
            "band_mode": _scoped_status(self._grid4_scoped, key, band, mode, True, True),
        }

    def is_new_dxcc(self, dxcc_id: Optional[int]) -> Optional[bool]:
        if dxcc_id is None or not self.has_column("dxcc_id"):
            return None
        return dxcc_id not in self.worked_dxcc_ids

    def is_new_cq_zone(self, cq_zone: Optional[str]) -> Optional[bool]:
        if cq_zone is None or not self.has_column("cq_zone"):
            return None
        return str(cq_zone).lstrip("0") not in self.worked_cq_zones

    def is_new_grid4(self, grid: Optional[str]) -> Optional[bool]:
        if not grid or len(grid) < 4 or not self.has_column("grid"):
            return None
        return grid[:4].upper() not in self.worked_grids4

    # -- per-callsign point lookup -------------------------------------------

    def lookup(self, callsign: str, base_callsign: Optional[str] = None, band: Optional[str] = None, mode: Optional[str] = None) -> CallStatus:
        status = CallStatus(callsign=callsign)
        if not self._columns or "call" not in self._columns:
            status.error = "qso_table has no readable 'call' column (check database_path / qso_table config)"
            return status

        candidates = [callsign]
        if base_callsign and base_callsign != callsign:
            candidates.append(base_callsign)

        select_cols = ["call"]
        for c in ("dxcc_country", "dxcc_id", "cq_zone", "band_rx", "mode", "qsl_received", "grid"):
            if self.has_column(c):
                select_cols.append(c)
        col_list = ", ".join(select_cols)

        placeholders = ",".join("?" for _ in candidates)
        sql = f"SELECT {col_list} FROM {self.qso_table} WHERE call IN ({placeholders})"

        try:
            rows = self._execute(sql, tuple(c.upper() for c in candidates))
        except Exception as exc:
            log.exception("Lookup query failed for %s", callsign)
            status.error = str(exc)
            return status

        if not rows:
            return status  # never worked -- all flags stay False/None

        status.worked_before = True
        status.qso_count = len(rows)
        row_dicts = [dict(zip(select_cols, row)) for row in rows]

        first = row_dicts[0]
        status.dxcc_country = first.get("dxcc_country")
        status.dxcc_id = first.get("dxcc_id")
        status.cq_zone = first.get("cq_zone")
        if "grid" in select_cols:
            status.grids_worked = sorted({r.get("grid") for r in row_dicts if r.get("grid")})

        if band and "band_rx" in select_cols:
            status.worked_this_band = any(r.get("band_rx") == band for r in row_dicts)
        if mode and "mode" in select_cols:
            status.worked_this_mode = any(r.get("mode") == mode for r in row_dicts)
        if band and mode and "band_rx" in select_cols and "mode" in select_cols:
            status.worked_this_band_and_mode = any(
                r.get("band_rx") == band and r.get("mode") == mode for r in row_dicts
            )
        if "qsl_received" in select_cols:
            def _confirmed(qsl):
                if not qsl:
                    return False
                qsl_u = qsl.upper()
                return any(tag in qsl_u for tag in ("LOTW", "EQSL", "CARD"))
            status.confirmed_ever = any(_confirmed(r.get("qsl_received")) for r in row_dicts)
            status.confirmed_lotw_ever = any(_is_lotw(r.get("qsl_received")) for r in row_dicts)
            if band:
                status.confirmed_this_band = any(
                    r.get("band_rx") == band and _confirmed(r.get("qsl_received")) for r in row_dicts
                )
                status.confirmed_lotw_this_band = any(
                    r.get("band_rx") == band and _is_lotw(r.get("qsl_received")) for r in row_dicts
                )
            if mode:
                status.confirmed_lotw_this_mode = any(
                    r.get("mode") == mode and _is_lotw(r.get("qsl_received")) for r in row_dicts
                )
            if band and mode:
                status.confirmed_lotw_band_and_mode = any(
                    r.get("band_rx") == band and r.get("mode") == mode and _is_lotw(r.get("qsl_received"))
                    for r in row_dicts
                )

        return status

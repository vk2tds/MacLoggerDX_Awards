#!/usr/bin/env python3
"""
log_writer.py -- the one WRITE path to MacLoggerDX's live SQLite log in this
codebase. Everything else here (log_status.py, qsl_helper.py,
macloggerdx_awards.py) is deliberately read-only.

Why this exists: WSJT-X's UDP API has no way to confirm its own "Log QSO"
dialog remotely -- QSOLogged/LoggedADIF are outgoing-only notifications
sent *after* a human clicks OK on the machine WSJT-X is running on. When
operating through the Remote tab from somewhere else, that dialog can't be
reached at all. This module lets the Remote tab build a QSO record from
WSJT-X's own live Status fields and write it directly, standing in for
that confirmation step.

Always intended to be used with a human review step first (the Remote tab
shows an editable preview before calling insert_qso()) -- this module
itself doesn't decide anything, it just writes what it's given, plus a
best-effort duplicate check since WSJT-X's own dialog might *also*
eventually get confirmed for the same contact if left sitting unattended.
"""

from __future__ import annotations

import dataclasses
import logging
import sqlite3
import time
from typing import Optional

log = logging.getLogger("log_writer")

# How close in time a same call+band+mode QSO must be to count as a likely
# duplicate of one we're about to insert.
DUPLICATE_WINDOW_S = 30 * 60


@dataclasses.dataclass
class QsoRecord:
    my_call: str
    my_grid: str
    call: str
    grid: str
    mode: str
    band: str
    tx_frequency_mhz: Optional[float] = None
    rst_sent: str = ""
    rst_received: str = ""
    dxcc_country: Optional[str] = None
    dxcc_id: Optional[int] = None
    cq_zone: Optional[str] = None
    qso_start: Optional[float] = None  # epoch seconds
    qso_done: Optional[float] = None
    comments: str = ""


def _connect_rw(database_path: str) -> sqlite3.Connection:
    # No ?mode=ro -- this is deliberately the one place in this codebase
    # that opens the log for writing. timeout so a transient lock (e.g.
    # MacLoggerDX itself mid-write) is waited out rather than raising
    # immediately.
    return sqlite3.connect(database_path, timeout=10.0)


def find_possible_duplicate(
    database_path: str, qso_table: str, call: str, band: str, mode: str, near_epoch: float,
    window_s: float = DUPLICATE_WINDOW_S,
) -> Optional[dict]:
    """Read-only pre-check: is there already a QSO with this call/band/mode
    within `window_s` seconds of `near_epoch`? Doesn't block anything by
    itself -- the caller decides what to do with the answer."""
    conn = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True, timeout=5.0)
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT pk, qso_start, qso_done FROM {qso_table} "
            f"WHERE call = ? AND band_tx = ? AND mode = ? AND qso_start BETWEEN ? AND ? "
            f"ORDER BY qso_start DESC LIMIT 1",
            (call.upper(), band, mode, near_epoch - window_s, near_epoch + window_s),
        )
        row = cur.fetchone()
        return {"pk": row[0], "qso_start": row[1], "qso_done": row[2]} if row else None
    finally:
        conn.close()


def insert_qso(database_path: str, qso_table: str, rec: QsoRecord) -> int:
    """Insert one QSO row. Returns the new row's pk.

    Only sets columns this codebase can actually populate correctly --
    notably leaves latitude/longitude/distance/azimuth/elevation unset,
    matching the existing convention in this log for QSOs where only a
    4-character grid is known (which is all a WSJT-X exchange ever gives
    us): those columns already read 0.0 for such rows, so an unset column
    (SQLite default) is consistent with what's already there rather than a
    new kind of gap.
    """
    now = time.time()
    qso_start = rec.qso_start if rec.qso_start is not None else now
    qso_done = rec.qso_done if rec.qso_done is not None else now

    values = {
        "my_call": rec.my_call,
        "my_grid": rec.my_grid,
        "call": rec.call,
        "grid": rec.grid,
        "dxcc_country": rec.dxcc_country,
        "dxcc_id": rec.dxcc_id,
        "cq_zone": rec.cq_zone,
        "mode": rec.mode,
        "band_rx": rec.band,
        "band_tx": rec.band,
        "rst_sent": rec.rst_sent,
        "rst_received": rec.rst_received,
        "qsl_sent": "",
        "qsl_received": "",
        "comments": rec.comments,
        "qso_start": qso_start,
        "qso_done": qso_done,
        "tx_frequency": rec.tx_frequency_mhz,
        "rx_frequency": rec.tx_frequency_mhz,
    }

    conn = _connect_rw(database_path)
    try:
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({qso_table})")
        available = {r[1] for r in cur.fetchall()}
        cols = [c for c in values if c in available and values[c] is not None]
        if "call" not in cols or "my_call" not in cols:
            raise ValueError(f"{qso_table} is missing expected columns (call/my_call) -- refusing to insert")
        placeholders = ",".join("?" for _ in cols)
        col_list = ",".join(cols)
        cur.execute(
            f"INSERT INTO {qso_table} ({col_list}) VALUES ({placeholders})",
            [values[c] for c in cols],
        )
        conn.commit()
        pk = cur.lastrowid
        log.info("Inserted QSO pk=%s call=%s band=%s mode=%s", pk, rec.call, rec.band, rec.mode)
        return pk
    finally:
        conn.close()

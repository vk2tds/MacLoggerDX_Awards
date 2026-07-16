#!/usr/bin/env python3
"""
qso_queue.py -- a small JSON-backed pending list for QSOs logged remotely
through the Remote tab, waiting to be pushed into MacLoggerDX.

Why this exists: writing directly into MacLoggerDX's SQLite log (the
original approach) turned out not to work reliably -- a test insert never
persisted, even surviving a MacLoggerDX restart. MacLoggerDX already has
its own working QSO ingestion (from WSJT-X UDP broadcasts and its native
`importADIF` AppleScript command -- see macloggerdx_bridge.py), so instead
of bypassing it we queue here and feed that existing path.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import threading
import time
from typing import Optional

log = logging.getLogger("qso_queue")


@dataclasses.dataclass
class QueueEntry:
    id: int
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
    qso_start: Optional[float] = None
    qso_done: Optional[float] = None
    comments: str = ""
    queued_at: float = 0.0
    status: str = "pending"  # pending | sent | error
    error: Optional[str] = None


class QsoQueue:
    def __init__(self, path: str):
        self.path = path
        # Reentrant: send()/delete() call _load_locked() while already
        # holding this lock (same pattern as qsl_helper.QslMethods, and the
        # same bug class to avoid -- see that module's history).
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

    def add(self, fields: dict) -> dict:
        with self._lock:
            entries = self._load_locked()
            next_id = (max((e["id"] for e in entries), default=0)) + 1
            entry = {
                "id": next_id,
                "my_call": fields.get("my_call", ""),
                "my_grid": fields.get("my_grid", ""),
                "call": fields.get("call", ""),
                "grid": fields.get("grid", ""),
                "mode": fields.get("mode", ""),
                "band": fields.get("band", ""),
                "tx_frequency_mhz": fields.get("tx_frequency_mhz"),
                "rst_sent": fields.get("rst_sent", ""),
                "rst_received": fields.get("rst_received", ""),
                "dxcc_country": fields.get("dxcc_country"),
                "dxcc_id": fields.get("dxcc_id"),
                "cq_zone": fields.get("cq_zone"),
                "qso_start": fields.get("qso_start"),
                "qso_done": fields.get("qso_done"),
                "comments": fields.get("comments", ""),
                "queued_at": time.time(),
                "status": "pending",
                "error": None,
            }
            entries.append(entry)
            self._save(entries)
            return entry

    def mark_sent(self, entry_id: int) -> Optional[dict]:
        with self._lock:
            entries = self._load_locked()
            for e in entries:
                if e["id"] == entry_id:
                    e["status"] = "sent"
                    e["error"] = None
                    self._save(entries)
                    return e
            return None

    def mark_error(self, entry_id: int, message: str) -> Optional[dict]:
        with self._lock:
            entries = self._load_locked()
            for e in entries:
                if e["id"] == entry_id:
                    e["status"] = "error"
                    e["error"] = message
                    self._save(entries)
                    return e
            return None

    def get(self, entry_id: int) -> Optional[dict]:
        for e in self.load():
            if e["id"] == entry_id:
                return e
        return None

    def delete(self, entry_id: int) -> list:
        with self._lock:
            entries = [e for e in self._load_locked() if e["id"] != entry_id]
            self._save(entries)
            return entries

    def pending_ids(self) -> list:
        return [e["id"] for e in self.load() if e["status"] == "pending"]

    def clear_sent(self) -> list:
        with self._lock:
            entries = [e for e in self._load_locked() if e["status"] != "sent"]
            self._save(entries)
            return entries

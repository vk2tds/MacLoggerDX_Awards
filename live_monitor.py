#!/usr/bin/env python3
"""
live_monitor.py -- the JT-Bridge-like piece: a background thread listens
for WSJT-X UDP decodes, cross-references each heard callsign against the
MacLoggerDX log + ARRL DXCC list, and streams the results to any browser
tab that has /live open, over a WebSocket.

Wiring this into the existing macloggerdx_awards Flask app (see app.py):

    from flask_sock import Sock
    import live_monitor

    sock = Sock(app)
    live_monitor.init_live_monitor(app, sock, live_monitor.LiveMonitorConfig(
        database_path=analysis.database_name,
        qso_table=analysis.qso_table,
        dxcc_file=analysis.dxcc_file,
        my_call="VK2TDS",
    ))

Then add a nav link to url_for('live.live_view').

See INTEGRATION.md in this folder for the exact app.py diff.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import logging
import os
import queue
import threading
import time
from collections import deque
from typing import Optional

from flask import Blueprint, jsonify, render_template, request

from wsjtx_udp import (
    MSG_CLEAR,
    MSG_DECODE,
    MSG_QSO_LOGGED,
    MSG_STATUS,
    WsjtxMessage,
    build_clear,
    build_configure,
    build_free_text,
    build_halt_tx,
    build_reply,
    run_listener,
)
from ft8_parser import parse_message, base_callsign
from dxcc_lookup import DxccResolver
from log_status import LogStatusChecker
import qsl_helper
import unknown_dxcc_log

log = logging.getLogger("live_monitor")

_BAND_TABLE = [
    (1.8, 2.0, "160M"), (3.5, 4.0, "80M"), (5.3, 5.4, "60M"), (7.0, 7.3, "40M"),
    (10.1, 10.15, "30M"), (14.0, 14.35, "20M"), (18.068, 18.168, "17M"),
    (21.0, 21.45, "15M"), (24.89, 24.99, "12M"), (28.0, 29.7, "10M"),
    (50.0, 54.0, "6M"), (70.0, 70.5, "4M"), (144.0, 148.0, "2M"),
]

# Fallback T/R period per mode, used only when WSJT-X's last reported
# Status didn't have a usable value (it sometimes reports the quint32
# "not available" sentinel 0xFFFFFFFF for this field).
_DEFAULT_TR_PERIOD_BY_MODE = {
    "FT8": 15, "FT4": 6, "JT9": 15, "JT65": 60, "MSK144": 15,
    "Q65": 60, "WSPR": 120, "FST4": 60, "FST4W": 120,
}
_SANE_TR_PERIOD_RANGE = (1, 1800)
_SANE_FREQ_TOLERANCE_RANGE = (1, 1000)


def freq_to_band(hz: Optional[int]) -> Optional[str]:
    if not hz:
        return None
    mhz = hz / 1_000_000.0
    for lo, hi, name in _BAND_TABLE:
        if lo <= mhz <= hi:
            return name
    return None


def _json_safe(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is None or isinstance(v, (str, int, float, bool))}


@dataclasses.dataclass
class LiveMonitorConfig:
    database_path: str
    qso_table: str
    dxcc_file: str
    my_call: str = ""
    udp_host: str = "127.0.0.1"
    udp_port: int = 2237
    multicast_group: Optional[str] = None
    # Replayed to any page that (re)loads /live/history -- this is what a
    # browser tab rebuilds its whole in-memory view from (DX Monitor's
    # entity list/activity boxes, Logbook's Live toggle, etc.) whenever it's
    # reloaded, e.g. after the browser discards a backgrounded tab and the
    # user switches back to it. 300 was too small in practice -- on a busy
    # band with lots of simultaneous decodes it could be exhausted within a
    # couple of minutes, so a tab reload after being away just 10-15 minutes
    # could lose everything older than that. Bumped up to comfortably cover
    # a good chunk of DX Monitor's 90-minute activity-box window even on a
    # busy multi-signal band (confirmed live 2026-08-02 this was the actual
    # cause of a reported "history just disappeared" complaint -- the app
    # process itself had been running continuously the whole time, so it
    # wasn't a server restart).
    history_size: int = 5000
    refresh_worked_sets_interval_s: float = 300.0

    @property
    def my_call_area(self) -> Optional[str]:
        import re
        m = re.search(r"\d", self.my_call.split("/")[0]) if self.my_call else None
        return m.group(0) if m else None


class LiveMonitor:
    def __init__(self, config: LiveMonitorConfig):
        self.config = config
        self.status_checker = LogStatusChecker(config.database_path, config.qso_table)
        try:
            self.dxcc_resolver: Optional[DxccResolver] = DxccResolver(config.dxcc_file)
        except Exception:
            log.exception("Could not load DXCC resolver -- continuing without prefix lookups")
            self.dxcc_resolver = None
        self.status_checker.refresh_worked_sets()

        self.history = deque(maxlen=config.history_size)
        # DX Monitor's own replay buffer -- deliberately separate from
        # self.history. Every decode goes into both, but only self.history is
        # wiped by WSJT-X's own Erase button (see MSG_CLEAR below): Live
        # Monitor is meant to mirror WSJT-X's Band Activity/Rx Frequency
        # windows, so clearing it on Erase is correct, but DX Monitor is
        # explicitly meant to keep a longer history *regardless* of Erase
        # (see templates/live_entities.html's "Deliberately NOT listening for
        # 'clear'" comment). That client-side design only covered decodes
        # arriving while the page was already open -- a page (re)load still
        # replayed the same shared, Erase-wiped self.history, so DX Monitor's
        # accumulated history could still vanish on reload/reconnect shortly
        # after an Erase. A real user report ("history disappeared... I think
        # it happened when I pressed erase on WSJT-X") confirmed this.
        self.dx_history = deque(maxlen=config.history_size)
        self.wsjtx_status: dict = {}
        self.cq_filter_enabled = True
        self._recent_decodes: deque = deque()
        self._recent_decodes_set: set = set()

        # Last grid square actually seen from each call (keyed by base
        # callsign), for entity resolution only -- e.g. VK0's Heard I. vs
        # Macquarie I. vs Antarctica disambiguation (see dxcc_lookup.py)
        # needs a grid, but most decodes for an ongoing QSO (signal
        # report/RRR/73 exchanges) carry no grid at all. Without this,
        # _compute_status() re-resolves the entity from scratch on every
        # decode using only *that* decode's own grid, so a station that
        # correctly resolved to Antarctica off an earlier CQ (which does
        # carry a grid) flips back to VK0's ambiguous-default Heard I. as
        # soon as a grid-less follow-up decode arrives -- confirmed live
        # 2026-09-01 with VK0DS on 15M reverting to "Heard I." mid-QSO.
        self._last_grid_by_call: dict = {}

        self._clients_lock = threading.Lock()
        self._clients: list = []
        self._last_cache_refresh = time.time()
        self._logbook_mtime_seen: Optional[float] = None
        self._thread: Optional[threading.Thread] = None
        self._logbook_watchdog_thread: Optional[threading.Thread] = None
        self._loop = None
        self._transport = None
        # Updated on every inbound message (not just decodes) so the Remote
        # control panel always has somewhere current to send commands, even
        # before the user has double-clicked anything.
        self._last_wsjtx_addr: Optional[tuple] = None
        self._last_wsjtx_id: Optional[str] = None

    # -- lifecycle -------------------------------------------------------

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, name="wsjtx-udp-listener", daemon=True)
        self._thread.start()
        self._logbook_watchdog_thread = threading.Thread(
            target=self._logbook_watchdog_loop, name="logbook-watchdog", daemon=True,
        )
        self._logbook_watchdog_thread.start()

    def _run_loop(self):
        import asyncio
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except Exception:
            log.exception("WSJT-X UDP listener loop exited unexpectedly")

    async def _main(self):
        import asyncio
        self._transport = await run_listener(
            self._on_message,
            host=self.config.udp_host,
            port=self.config.udp_port,
            multicast_group=self.config.multicast_group,
        )
        while True:
            await asyncio.sleep(3600)

    # -- sending commands back to WSJT-X, on the same socket we're
    # listening with --------------------------------------------------------

    def _send_to_wsjtx(self, label: str, data: bytes, dest: Optional[tuple] = None) -> bool:
        dest = dest or self._last_wsjtx_addr
        if not dest or self._transport is None or self._loop is None:
            log.warning("Cannot send WSJT-X %s -- listener not ready or no known WSJT-X address yet", label)
            return False
        self._loop.call_soon_threadsafe(self._transport.sendto, data, dest)
        log.info("Sent WSJT-X %s to %s", label, dest)
        return True

    def send_reply(self, event: dict) -> bool:
        """Double-click-to-call: mimics double-clicking a decode in WSJT-X."""
        raw = event.get("raw") or {}
        source = event.get("source")
        if not source:
            log.warning("Cannot send WSJT-X reply -- event has no source address")
            return False
        try:
            data = build_reply(
                client_id=event.get("wsjtx_id") or "WSJT-X",
                time_ms=raw.get("time_ms") or 0,
                snr=raw.get("snr") or 0,
                delta_time_s=raw.get("delta_time_s") or 0.0,
                delta_freq_hz=raw.get("delta_freq_hz") or 0,
                mode=raw.get("mode") or "",
                message=raw.get("message") or "",
                low_confidence=bool(raw.get("low_confidence")),
            )
        except Exception:
            log.exception("Failed to build WSJT-X reply for %s", raw.get("message"))
            return False
        return self._send_to_wsjtx(f"reply {raw.get('message')!r}", data, tuple(source))

    def handle_reply_action(self, event: dict) -> bool:
        """Entry point for the "double-click a decode to call" gesture from
        the front end. WSJT-X's Reply UDP message is hard-filtered by WSJT-X
        itself to only accept messages that look like a CQ or QRZ call (per
        a WSJT-X developer on the wsjt-devel list) -- it silently ignores
        anything else, regardless of what any external tool sends. For a
        non-CQ decode we fall back to Configure, which sets DX Call/Grid
        directly and isn't subject to that filter."""
        if event.get("is_cq"):
            return self.send_reply(event)
        return self.send_call_via_configure(event)

    def send_call_via_configure(self, event: dict) -> bool:
        call = event.get("call")
        if not call:
            log.warning("Cannot Configure-call -- event has no call")
            return False
        mode = event.get("mode") or self.wsjtx_status.get("mode") or "FT8"
        grid = event.get("grid") or ""
        rx_df = event.get("delta_freq_hz")
        if not isinstance(rx_df, int):
            rx_df = self.wsjtx_status.get("rx_df") if isinstance(self.wsjtx_status.get("rx_df"), int) else 1500

        tr_period = self.wsjtx_status.get("tr_period")
        if not (isinstance(tr_period, int) and _SANE_TR_PERIOD_RANGE[0] <= tr_period <= _SANE_TR_PERIOD_RANGE[1]):
            tr_period = _DEFAULT_TR_PERIOD_BY_MODE.get(mode, 15)

        freq_tolerance = self.wsjtx_status.get("frequency_tolerance")
        if not (isinstance(freq_tolerance, int)
                and _SANE_FREQ_TOLERANCE_RANGE[0] <= freq_tolerance <= _SANE_FREQ_TOLERANCE_RANGE[1]):
            freq_tolerance = 10

        return self.send_configure(
            mode=mode,
            frequency_tolerance=freq_tolerance,
            submode=self.wsjtx_status.get("sub_mode"),
            fast_mode=bool(self.wsjtx_status.get("fast_mode")),
            tr_period=tr_period,
            rx_df=rx_df,
            dx_call=call,
            dx_grid=grid,
            generate_messages=True,
        )

    def send_free_text(self, text: str, send: bool = False) -> bool:
        try:
            data = build_free_text(client_id=self._last_wsjtx_id or "WSJT-X", text=text, send=send)
        except Exception:
            log.exception("Failed to build WSJT-X FreeText for %r", text)
            return False
        return self._send_to_wsjtx(f"FreeText {text!r} (send={send})", data)

    def send_clear(self, window: int = 0) -> bool:
        try:
            data = build_clear(client_id=self._last_wsjtx_id or "WSJT-X", window=window)
        except Exception:
            log.exception("Failed to build WSJT-X Clear")
            return False
        return self._send_to_wsjtx("Clear", data)

    def send_halt_tx(self, auto_tx_only: bool = False) -> bool:
        try:
            data = build_halt_tx(client_id=self._last_wsjtx_id or "WSJT-X", auto_tx_only=auto_tx_only)
        except Exception:
            log.exception("Failed to build WSJT-X HaltTx")
            return False
        return self._send_to_wsjtx("HaltTx", data)

    def send_configure(self, **kwargs) -> bool:
        try:
            data = build_configure(client_id=self._last_wsjtx_id or "WSJT-X", **kwargs)
        except Exception:
            log.exception("Failed to build WSJT-X Configure with %r", kwargs)
            return False
        return self._send_to_wsjtx(f"Configure {kwargs}", data)

    # -- WSJT-X message handling -----------------------------------------

    def _on_message(self, msg: WsjtxMessage):
        self._last_wsjtx_addr = msg.source
        if msg.id:
            self._last_wsjtx_id = msg.id
        try:
            if msg.type == MSG_DECODE:
                self._handle_decode(msg)
            elif msg.type == MSG_STATUS:
                self.wsjtx_status = msg.fields
                self._broadcast({"kind": "status", **_json_safe(msg.fields)})
            elif msg.type == MSG_QSO_LOGGED:
                self._broadcast({"kind": "qso_logged", "dx_call": msg.fields.get("dx_call")})
                self._last_cache_refresh = 0  # force a cache refresh on the next decode
            elif msg.type == MSG_CLEAR:
                # WSJT-X's "Erase" button -- regardless of which window it
                # says to clear (Band Activity / Rx Frequency / both), wipe
                # both Live Monitor tables to match.
                self.history.clear()
                self._recent_decodes.clear()
                self._recent_decodes_set.clear()
                self._broadcast({"kind": "clear"})
        except Exception:
            log.exception("Error handling WSJT-X %s message", msg.type_name)

    def _maybe_refresh_caches(self):
        if time.time() - self._last_cache_refresh > self.config.refresh_worked_sets_interval_s:
            self._last_cache_refresh = time.time()
            self.status_checker.refresh_worked_sets()

    # A station's orange/green colour on DX Monitor was being permanently
    # frozen to whatever the logbook said the moment that specific decode
    # arrived -- a QSL received/logged 10 minutes later never updated it,
    # since nothing recomputes an *existing* entry, only fresh decodes ever
    # get looked up. Confirmed live 2026-08-19: a station's real, already-
    # recorded LoTW confirmation stayed invisible on DX Monitor until it
    # happened to be heard again. Polling the logbook file's own mtime
    # (rather than waiting for the unrelated 5-minute refresh_worked_sets
    # timer, or requiring MacLoggerDX to notify this process somehow) is
    # the only signal available -- MacLoggerDX is a separate app writing
    # directly to this SQLite file, with no push mechanism of its own.
    LOGBOOK_POLL_INTERVAL_S = 5.0

    def _logbook_mtime(self) -> Optional[float]:
        try:
            return os.path.getmtime(self.config.database_path)
        except OSError:
            return None

    def _logbook_watchdog_loop(self):
        self._logbook_mtime_seen = self._logbook_mtime()
        while True:
            time.sleep(self.LOGBOOK_POLL_INTERVAL_S)
            mtime = self._logbook_mtime()
            if mtime is not None and mtime != self._logbook_mtime_seen:
                self._logbook_mtime_seen = mtime
                try:
                    self._refresh_dx_history_status()
                except Exception:
                    log.exception("Error refreshing DX Monitor status after a logbook change")

    def _refresh_dx_history_status(self):
        """Recomputes status for every call+band DX Monitor currently knows
        about and pushes out only what actually changed -- not just to
        connected clients (a 'status_refresh' broadcast, so an on-screen
        entry recolours without needing a fresh decode) but also into the
        stored dx_history events themselves, so a page reload's replay
        reflects the same refreshed status instead of reverting to
        whatever was true at decode time."""
        self.status_checker.refresh_worked_sets()
        self._last_cache_refresh = time.time()

        # Snapshot -- avoid iterating self.dx_history while the UDP listener
        # thread might be appending to it concurrently.
        snapshot = list(self.dx_history)
        latest_by_key = {}
        for ev in snapshot:
            if ev.get("call"):
                latest_by_key[(ev["call"], ev.get("band"))] = ev

        updates = []
        for (call, band), sample_ev in latest_by_key.items():
            base = sample_ev.get("base_call") or call
            grid = sample_ev.get("grid")
            entity_grid = grid or self._last_grid_by_call.get(base)
            fresh = self._compute_status(
                call, base, band, sample_ev.get("mode"), grid, entity_grid=entity_grid,
            )
            if all(sample_ev.get(k) == v for k, v in fresh.items()):
                continue
            old_dxcc_name = sample_ev.get("dxcc_name")
            for ev in snapshot:
                if ev.get("call") == call and ev.get("band") == band:
                    ev.update(fresh)
            updates.append({"call": call, "band": band, "old_dxcc_name": old_dxcc_name, **fresh})

        if updates:
            log.info("Logbook changed -- refreshed status for %d DX Monitor entr%s", len(updates), "y" if len(updates) == 1 else "ies")
            self._broadcast({"kind": "status_refresh", "updates": updates})

    def _compute_status(self, call, base, band, mode, grid, entity_grid=None):
        """Every field derivable from the DXCC resolver + logbook for one
        call/base/band/mode/grid combo -- shared between _handle_decode()
        (a fresh WSJT-X decode) and _refresh_dx_history_status() (an
        existing DX Monitor entry getting recomputed after the logbook
        changes, with no new decode involved). Keep in sync: any field
        added to a live decode's status here should also end up in
        _refresh_dx_history_status()'s broadcast, or a logbook update
        won't actually update it on screen.

        `entity_grid` is used only for DXCC entity resolution (the VK0
        special case) and defaults to `grid` when not given -- callers that
        have a better last-known grid for this call (this decode's own
        message carried none) can pass it separately, since `grid`/
        `is_new_grid`/`grid_status_scopes` below must still reflect what
        *this* decode actually carried, not a stale fallback."""
        if entity_grid is None:
            entity_grid = grid
        entity = None
        if self.dxcc_resolver is not None and (base or call):
            entity = self.dxcc_resolver.lookup(base or call, grid=entity_grid)
        db_status = self.status_checker.lookup(call, base_callsign=base, band=band, mode=mode) if call else None

        is_new_dxcc = None
        dxcc_id_for_flag = entity.dxcc_id if entity else (db_status.dxcc_id if db_status else None)
        if dxcc_id_for_flag is not None:
            is_new_dxcc = self.status_checker.is_new_dxcc(dxcc_id_for_flag)

        # Green/orange/red (confirmed/worked/none) status, for all four
        # band/mode scope combinations at once -- the Live Monitor page
        # picks which one to display client-side so the Band/Mode checkboxes
        # can re-colour instantly without a round trip.
        call_status_scopes = db_status.status_all_scopes() if db_status else {
            "overall": "none", "band": "none", "mode": "none", "band_mode": "none",
        }
        entity_status_scopes = self.status_checker.entity_status_all_scopes(dxcc_id_for_flag, band, mode)
        grid_status_scopes = self.status_checker.grid_status_all_scopes(grid, band, mode)
        dxcc_name = entity.name if entity else (db_status.dxcc_country if db_status else None)

        return {
            "dxcc_name": dxcc_name,
            "cq_zone": entity.cq_zone if entity else (db_status.cq_zone if db_status else None),
            "continent": entity.continent if entity else None,
            "worked_before": db_status.worked_before if db_status else None,
            "worked_this_band": db_status.worked_this_band if db_status else None,
            "confirmed_ever": db_status.confirmed_ever if db_status else None,
            "confirmed_this_band": db_status.confirmed_this_band if db_status else None,
            "is_new_dxcc": is_new_dxcc,
            "is_new_grid": self.status_checker.is_new_grid4(grid) if grid else None,
            "db_error": db_status.error if db_status else None,
            "call_status": call_status_scopes,
            "entity_status": entity_status_scopes,
            "grid_status": grid_status_scopes,
        }

    def _handle_decode(self, msg: WsjtxMessage):
        fields = msg.fields
        text = fields.get("message") or ""

        # WSJT-X (and the multicast link it's fed through) can emit the same
        # decode more than once in a period -- e.g. a strong signal decoded
        # on more than one audio bin, or a JT-Bridge-style relay re-sending
        # what it received. Same period + same text is always the same
        # over-the-air transmission, so collapse repeats before we do any
        # lookups or broadcast to the live table.
        dedup_key = (fields.get("time_ms"), text)
        if dedup_key in self._recent_decodes_set:
            return
        self._recent_decodes_set.add(dedup_key)
        self._recent_decodes.append(dedup_key)
        if len(self._recent_decodes) > 200:
            oldest = self._recent_decodes.popleft()
            self._recent_decodes_set.discard(oldest)

        parsed = parse_message(text)
        self._maybe_refresh_caches()

        call = parsed.subject_call
        base = base_callsign(call) if call else None
        band = freq_to_band(self.wsjtx_status.get("dial_frequency_hz"))
        mode = fields.get("mode")

        if parsed.grid and (base or call):
            self._last_grid_by_call[base or call] = parsed.grid
        entity_grid = parsed.grid or (self._last_grid_by_call.get(base or call) if (base or call) else None)
        status = self._compute_status(call, base, band, mode, parsed.grid, entity_grid=entity_grid)

        cq_area_mismatch = False
        if (
            self.cq_filter_enabled
            and parsed.is_cq
            and parsed.cq_directed
            and parsed.cq_directed.isdigit()
            and self.config.my_call_area
        ):
            cq_area_mismatch = parsed.cq_directed != self.config.my_call_area

        if status["dxcc_name"] is None and call:
            unknown_dxcc_log.record(call, band=band, mode=mode, message=text)

        event = {
            "kind": "decode",
            # Real wall-clock time this decode was received, in epoch ms. Distinct
            # from time_ms (WSJT-X's own ms-since-midnight-UTC field, unusable for
            # elapsed-time math across a day boundary or a page reload). Clients
            # replaying /live/history use this to compute a decode's true age
            # instead of stamping Date.now() (which made every replayed event
            # look like it just happened -- see project_live_history_buffer_size).
            "received_epoch_ms": int(time.time() * 1000),
            "time_ms": fields.get("time_ms"),
            "snr": fields.get("snr"),
            "delta_freq_hz": fields.get("delta_freq_hz"),
            "dial_frequency_hz": self.wsjtx_status.get("dial_frequency_hz"),
            "mode": mode,
            "band": band,
            "message": text,
            "is_cq": parsed.is_cq,
            "cq_directed": parsed.cq_directed,
            "cq_area_mismatch": cq_area_mismatch,
            "to_call": parsed.to_call,
            "call": call,
            "base_call": base,
            "grid": parsed.grid,
            "hashed": parsed.hashed,
            **status,
            # Everything needed to send a WSJT-X "Reply" (double-click to
            # call) for this exact decode -- see send_reply().
            "wsjtx_id": msg.id,
            "source": list(msg.source),
            "raw": {
                "time_ms": fields.get("time_ms"),
                "snr": fields.get("snr"),
                "delta_time_s": fields.get("delta_time_s"),
                "delta_freq_hz": fields.get("delta_freq_hz"),
                "mode": mode,
                "message": text,
                "low_confidence": fields.get("low_confidence"),
            },
        }
        self.history.append(event)
        self.dx_history.append(event)
        self._broadcast(event)

    # -- pub/sub for the websocket route ----------------------------------

    def _broadcast(self, event: dict):
        with self._clients_lock:
            targets = list(self._clients)
        for q in targets:
            q.put(event)

    def broadcast_event(self, event: dict):
        """Public entry point for other modules to push an event onto this
        same /live/ws fan-out (e.g. audio_spectrum.py's spectrum rows) --
        same "reuse the shared transport" precedent as wsjtx_remote.py.
        Deliberately doesn't touch self.history: that's only for the decode/
        status/qso_logged events /live/history replays on page load."""
        self._broadcast(event)

    def register_client(self) -> "queue.Queue":
        q: "queue.Queue" = queue.Queue()
        with self._clients_lock:
            self._clients.append(q)
        return q

    def unregister_client(self, q: "queue.Queue"):
        with self._clients_lock:
            if q in self._clients:
                self._clients.remove(q)

    def history_snapshot(self) -> list:
        return list(self.history)

    def dx_history_snapshot(self) -> list:
        return list(self.dx_history)


# ---------------------------------------------------------------------------
# Flask wiring
# ---------------------------------------------------------------------------

live_bp = Blueprint("live", __name__, template_folder="templates")
_monitor: Optional[LiveMonitor] = None


def get_monitor() -> Optional[LiveMonitor]:
    """Accessor for other blueprints (e.g. wsjtx_remote.py) that want to
    reuse the single shared UDP listener/transport rather than opening a
    second one."""
    return _monitor


def init_live_monitor(app, sock, config: LiveMonitorConfig) -> LiveMonitor:
    """Create the LiveMonitor, register the blueprint + websocket route,
    and start the background UDP listener thread. Call this once at
    startup (mirrors the existing `refresh()` call in app.py)."""
    global _monitor
    _monitor = LiveMonitor(config)
    # app.py calls this at true module level (unconditionally, not inside
    # `if __name__ == '__main__':`), so it runs once in Werkzeug's reloader
    # "watcher" process (before it forks into the reloader monitor loop) AND
    # again, separately, in every actual serving child it spawns on startup
    # and on every subsequent code-change restart. Without this guard, the
    # watcher process's own copy of this UDP thread/socket never gets
    # cleaned up (the watcher just loops forever, it doesn't exit) -- it
    # sits there permanently, bound to the same port via SO_REUSEPORT, and
    # the OS silently load-balances real incoming WSJT-X packets (decodes,
    # Status, and critically Erase/Clear) between it and whichever child is
    # actually driving the browser UI. That's a real, confirmed-live bug:
    # `lsof -nP -iUDP:2237` showed two live Python processes both bound to
    # the port, and a decode sent straight at 127.0.0.1:2237 was silently
    # swallowed (delivered to the dead-end watcher instead) more than once
    # during testing -- almost certainly a real contributor to this app's
    # long-running "DX Monitor history disappeared" reports, since a decode
    # or Erase routed to the watcher is simply never seen by anything.
    # WERKZEUG_RUN_MAIN is only set to "true" by Werkzeug in the process
    # that's actually going to serve, so this reliably starts the listener
    # exactly once, in the right process -- correct as long as this app
    # always runs with the reloader enabled (it does: app.py hardcodes
    # debug=True with no toggle).
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        _monitor.start()
    app.register_blueprint(live_bp)

    @sock.route("/live/ws")
    def ws_live(ws):  # noqa: ANN001 -- flask_sock supplies this
        client_q = _monitor.register_client()
        stop = threading.Event()
        # Tracks whether *this* connection currently holds a spectrum
        # listener slot (audio_spectrum.py's lazy start/stop -- see its
        # module docstring), so an ungraceful disconnect (tab closed,
        # navigated away, crashed) still releases it via the finally block
        # below, same as unregister_client() already does for client_q.
        is_spectrum_listener = False

        def sender():
            while not stop.is_set():
                try:
                    event = client_q.get(timeout=1.0)
                except queue.Empty:
                    continue
                try:
                    ws.send(json.dumps(event))
                except Exception:
                    stop.set()
                    return

        sender_thread = threading.Thread(target=sender, daemon=True)
        sender_thread.start()
        try:
            # DX Monitor fetches its own (Erase-independent) replay buffer
            # via /live/dx_history before connecting here -- skip the
            # default history_snapshot() replay for it, or every historical
            # decode would be delivered twice (once via that fetch, once via
            # this loop), double-counting its activity boxes. Every other
            # /live/ws consumer (Live Monitor, Remote, Logbook, Waterfall)
            # has no separate history fetch of its own and still relies on
            # this replay for its initial state.
            if request.args.get("no_history") != "1":
                for event in _monitor.history_snapshot():
                    ws.send(json.dumps(event))
            while not stop.is_set():
                data = ws.receive()
                if data is None:
                    break
                try:
                    cmd = json.loads(data)
                except (TypeError, ValueError):
                    continue
                if not isinstance(cmd, dict):
                    continue
                action = cmd.get("action")
                if action == "reply":
                    _monitor.handle_reply_action(cmd.get("event") or {})
                elif action == "spectrum_listen" and not is_spectrum_listener:
                    import audio_spectrum  # local import -- avoids a circular import at module load
                    spectrum = audio_spectrum.get_spectrum()
                    if spectrum is not None:
                        spectrum.add_listener()
                        is_spectrum_listener = True
                elif action == "spectrum_unlisten" and is_spectrum_listener:
                    import audio_spectrum
                    spectrum = audio_spectrum.get_spectrum()
                    if spectrum is not None:
                        spectrum.remove_listener()
                    is_spectrum_listener = False
                elif action == "request_scan_cancel":
                    # Find/Scan runs entirely as a browser-JS loop (this
                    # server has no server-side scan process to stop) -- and
                    # each Dashboard tile is its own separate mounted
                    # instance with its own JS state, so a scan started in
                    # one "DX Monitor: Find" tile is invisible to a
                    # double-click in a *different* "DX Monitor: DXCC's"
                    # tile's own local variables. Pure fan-out relay: every
                    # connected client (whichever one is actually running a
                    # scan, if any) gets this and cancels its own loop --
                    # see static/live_entities.js's ctx.on('scan_cancel_requested', ...).
                    _monitor.broadcast_event({"kind": "scan_cancel_requested"})
                elif action == "scan_cancelled":
                    # Ack relay so a double-click elsewhere can wait for the
                    # actual scan (wherever it's running) to finish
                    # unwinding before sending its own tune, instead of
                    # racing it -- see static/live_entities.js.
                    _monitor.broadcast_event({"kind": "scan_cancelled_ack"})
        except Exception:
            pass
        finally:
            stop.set()
            _monitor.unregister_client(client_q)
            if is_spectrum_listener:
                import audio_spectrum
                spectrum = audio_spectrum.get_spectrum()
                if spectrum is not None:
                    spectrum.remove_listener()

    return _monitor


@live_bp.route("/live")
def live_view():
    return render_template(
        "live_monitor.html",
        my_call=_monitor.config.my_call if _monitor else "",
        udp_port=_monitor.config.udp_port if _monitor else 2237,
    )


@live_bp.route("/live/widget/selection")
def live_widget_selection():
    """Dashboard widget: just the selection toolbar (connected dot, my-call,
    CQ filter/hide-worked, band/mode scope, legend, status line) -- see
    templates/live_monitor_widget.html and dashboard.py's module docstring
    for the overall widget pattern. Renders the exact same markup/JS as the
    full page (templates/_live_monitor_body.html, static/live_monitor.js),
    the CQ/non-CQ tables are just hidden via CSS."""
    return render_template(
        "live_monitor_widget.html",
        widget_mode="selection",
        my_call=_monitor.config.my_call if _monitor else "",
        udp_port=_monitor.config.udp_port if _monitor else 2237,
    )


@live_bp.route("/live/widget/cq")
def live_widget_cq():
    """Dashboard widget: just the scrolling CQs table -- see
    live_widget_selection()'s docstring above for the pattern."""
    return render_template(
        "live_monitor_widget.html",
        widget_mode="cq",
        my_call=_monitor.config.my_call if _monitor else "",
        udp_port=_monitor.config.udp_port if _monitor else 2237,
    )


@live_bp.route("/live/widget/noncq")
def live_widget_noncq():
    """Dashboard widget: just the scrolling non-CQs table -- see
    live_widget_selection()'s docstring above for the pattern."""
    return render_template(
        "live_monitor_widget.html",
        widget_mode="noncq",
        my_call=_monitor.config.my_call if _monitor else "",
        udp_port=_monitor.config.udp_port if _monitor else 2237,
    )


@live_bp.route("/live/widget/merged")
def live_widget_merged():
    """Dashboard widget: CQs and non-CQs interleaved into a single list by
    time (not two tables side by side) -- for anyone who'd rather have one
    wide tile than two separate ones. See live_widget_selection()'s
    docstring above for the pattern."""
    return render_template(
        "live_monitor_widget.html",
        widget_mode="merged",
        my_call=_monitor.config.my_call if _monitor else "",
        udp_port=_monitor.config.udp_port if _monitor else 2237,
    )


@live_bp.route("/live/entities")
def live_entities_view():
    """Same live decode feed as Live Monitor (/live/history + /live/ws),
    grouped client-side by DXCC entity instead of shown as a flat log --
    see templates/live_entities.html. No server-side grouping needed since
    every decode event already carries dxcc_name/entity_status/call_status."""
    return render_template("live_entities.html")


@live_bp.route("/live/entities/widget/find")
def live_entities_widget_find():
    """Dashboard widget: just the Find box + toolbar (connected dot,
    Everything/Current band filter, Clear) -- see
    templates/live_entities_widget.html and dashboard.py's module docstring
    for the overall widget pattern. Renders the exact same markup/JS as the
    full page (templates/_live_entities_body.html, static/live_entities.js),
    the entities-list section is just hidden via CSS."""
    return render_template("live_entities_widget.html", widget_mode="find")


@live_bp.route("/live/entities/widget/list")
def live_entities_widget_list():
    """Dashboard widget: just the scrolling DXCC entities list -- see
    live_entities_widget_find()'s docstring above for the pattern."""
    return render_template("live_entities_widget.html", widget_mode="list")


# Disk-backed (JSON file, same convention as rigdial_presets.json/
# rigdial_config.json etc.) so a selection survives an app restart -- it
# used to be in-memory only, which meant it looked like it "went missing on
# refresh" any time the process happened to have restarted since it was last
# saved (e.g. Flask's debug-mode auto-reloader restarting on every code
# change during active development, or the process crashing/being
# relaunched) -- the browser refresh itself was never actually the cause,
# just the moment the loss became visible.
#
# preset_ids used to be "bands" (WSJT-X band-button label strings, e.g.
# "20") -- renamed once Find moved from clicking WSJT-X's own band buttons
# to tuning directly via rigctld against Frequencies-tab presets flagged
# "find" (see templates/live_entities.html), since entries are now preset
# ids, not band labels. Any old "bands" selection is simply not carried
# forward -- this is a small convenience cache, not data worth migrating.
#
# scanning: True for the whole time a Scan is actually running (set right
# after Scan starts, cleared once it genuinely stops -- normal finish,
# Cancel, or error). Purely a signal for the client: on page load, if this
# is still true, the page was showing a scan in progress the last time
# anyone saved this file -- almost always because the browser tab reloaded
# (macOS/browser tab-discarding on sleep or backgrounding is the common
# real-world trigger, not a crash) rather than because the user meant to
# stop it, so the client auto-resumes. The scan loop itself still only ever
# runs as client-side JS in one tab -- this doesn't make a scan survive the
# *server* going away mid-cycle, only a *browser tab* reload/discard, which
# was the actual reported problem (a real ~45s-cadence scan ran fine for
# 50+ minutes, then the tab did a full reload -- confirmed via the access
# log's page-load fetch signature -- and nothing then told the fresh page
# it was supposed to keep scanning).
_FIND_SCAN_STATE_FILE = "find_scan_config.json"
_find_scan_state = {"preset_ids": [], "tune_enabled": False, "loop": False, "scanning": False}


def _load_find_scan_state():
    try:
        with open(_FIND_SCAN_STATE_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return
    if isinstance(saved.get("preset_ids"), list):
        _find_scan_state["preset_ids"] = [str(b) for b in saved["preset_ids"]]
    if "tune_enabled" in saved:
        _find_scan_state["tune_enabled"] = bool(saved["tune_enabled"])
    if "loop" in saved:
        _find_scan_state["loop"] = bool(saved["loop"])
    if "scanning" in saved:
        _find_scan_state["scanning"] = bool(saved["scanning"])


def _save_find_scan_state():
    try:
        with open(_FIND_SCAN_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(_find_scan_state, f, indent=2)
    except OSError:
        log.warning("Could not save %s", _FIND_SCAN_STATE_FILE, exc_info=True)


_load_find_scan_state()


@live_bp.route("/live/find_config", methods=["GET", "POST"])
def live_find_config():
    """Persists the DX Monitor 'Find' box's preset selection + tune/loop
    toggles -- see templates/live_entities.html. Deliberately its own tiny
    endpoint rather than folded into /live/config, since it's Find-widget
    state, not a live-decode setting."""
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        changed = False
        if isinstance(body.get("preset_ids"), list):
            _find_scan_state["preset_ids"] = [str(b) for b in body["preset_ids"]]
            changed = True
        if "tune_enabled" in body:
            _find_scan_state["tune_enabled"] = bool(body["tune_enabled"])
            changed = True
        if "loop" in body:
            _find_scan_state["loop"] = bool(body["loop"])
            changed = True
        if "scanning" in body:
            _find_scan_state["scanning"] = bool(body["scanning"])
            changed = True
        if changed:
            _save_find_scan_state()
    return jsonify(_find_scan_state)


@live_bp.route("/live/spectrum_status")
def live_spectrum_status():
    # Local import to avoid a circular import -- audio_spectrum.py imports
    # this module to reach broadcast_event()/get_monitor().
    import audio_spectrum
    return jsonify(audio_spectrum.status())


@live_bp.route("/live/history")
def live_history():
    if _monitor is None:
        return jsonify([])
    return jsonify(_monitor.history_snapshot())


@live_bp.route("/live/dx_history")
def live_dx_history():
    """DX Monitor's own replay buffer -- see LiveMonitor.dx_history's
    docstring comment for why this is separate from /live/history (that one
    is wiped by WSJT-X's own Erase button; this one deliberately isn't)."""
    if _monitor is None:
        return jsonify([])
    return jsonify(_monitor.dx_history_snapshot())


@live_bp.route("/live/callsign/<call>")
def callsign_history(call):
    """Combined history for one callsign: MacLoggerDX log summary (worked/
    confirmed, bands, grids) plus every ALL.TXT exchange line ever indexed
    for them (reuses qsl_helper's shared cache rather than re-indexing)."""
    if _monitor is None:
        return jsonify({"error": "Live monitor not initialised"}), 503
    call = call.strip().upper()
    base = base_callsign(call) or call

    db_status = _monitor.status_checker.lookup(call, base_callsign=base)
    entity = _monitor.dxcc_resolver.lookup(call) if _monitor.dxcc_resolver else None

    lines = []
    cache = qsl_helper.get_cache()
    if cache is not None:
        rows = cache.find_exchange(call, near_epoch=None)
        for ts, rxtx, freq_mhz, mode, snr, dt, df, msg, raw in rows:
            lines.append({
                "ts": ts,
                "time": datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
                "rxtx": rxtx, "freq_mhz": freq_mhz, "mode": mode, "snr": snr, "msg": msg, "raw": raw,
            })

    return jsonify({
        "call": call,
        "worked_before": db_status.worked_before,
        "qso_count": db_status.qso_count,
        "confirmed_ever": db_status.confirmed_ever,
        "confirmed_lotw_ever": db_status.confirmed_lotw_ever,
        "dxcc_country": db_status.dxcc_country or (entity.name if entity else None),
        "dxcc_id": db_status.dxcc_id if db_status.dxcc_id is not None else (entity.dxcc_id if entity else None),
        "grids_worked": db_status.grids_worked,
        "db_error": db_status.error,
        "exchange_lines": lines,
        "exchange_count": len(lines),
    })


@live_bp.route("/live/config", methods=["GET", "POST"])
def live_config():
    if _monitor is None:
        return jsonify({"error": "live monitor not started"}), 503
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        if "cq_filter_enabled" in body:
            _monitor.cq_filter_enabled = bool(body["cq_filter_enabled"])
        if "my_call" in body and body["my_call"]:
            _monitor.config.my_call = str(body["my_call"]).upper()
    return jsonify({
        "my_call": _monitor.config.my_call,
        "my_call_area": _monitor.config.my_call_area,
        "cq_filter_enabled": _monitor.cq_filter_enabled,
        "udp_host": _monitor.config.udp_host,
        "udp_port": _monitor.config.udp_port,
        "wsjtx_status": _json_safe(_monitor.wsjtx_status),
        "last_cache_refresh": _monitor._last_cache_refresh,
    })

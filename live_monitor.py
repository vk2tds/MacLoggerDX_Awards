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
    history_size: int = 300
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
        self.wsjtx_status: dict = {}
        self.cq_filter_enabled = True
        self._recent_decodes: deque = deque()
        self._recent_decodes_set: set = set()

        self._clients_lock = threading.Lock()
        self._clients: list = []
        self._last_cache_refresh = time.time()
        self._thread: Optional[threading.Thread] = None
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

        entity = None
        if self.dxcc_resolver is not None and (base or call):
            entity = self.dxcc_resolver.lookup(base or call)

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
        grid_status_scopes = self.status_checker.grid_status_all_scopes(parsed.grid, band, mode)

        cq_area_mismatch = False
        if (
            self.cq_filter_enabled
            and parsed.is_cq
            and parsed.cq_directed
            and parsed.cq_directed.isdigit()
            and self.config.my_call_area
        ):
            cq_area_mismatch = parsed.cq_directed != self.config.my_call_area

        event = {
            "kind": "decode",
            "time_ms": fields.get("time_ms"),
            "snr": fields.get("snr"),
            "delta_freq_hz": fields.get("delta_freq_hz"),
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
            "dxcc_name": entity.name if entity else (db_status.dxcc_country if db_status else None),
            "cq_zone": entity.cq_zone if entity else (db_status.cq_zone if db_status else None),
            "continent": entity.continent if entity else None,
            "worked_before": db_status.worked_before if db_status else None,
            "worked_this_band": db_status.worked_this_band if db_status else None,
            "confirmed_ever": db_status.confirmed_ever if db_status else None,
            "confirmed_this_band": db_status.confirmed_this_band if db_status else None,
            "is_new_dxcc": is_new_dxcc,
            "is_new_grid": self.status_checker.is_new_grid4(parsed.grid) if parsed.grid else None,
            "db_error": db_status.error if db_status else None,
            "call_status": call_status_scopes,
            "entity_status": entity_status_scopes,
            "grid_status": grid_status_scopes,
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
        self._broadcast(event)

    # -- pub/sub for the websocket route ----------------------------------

    def _broadcast(self, event: dict):
        with self._clients_lock:
            targets = list(self._clients)
        for q in targets:
            q.put(event)

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
    _monitor.start()
    app.register_blueprint(live_bp)

    @sock.route("/live/ws")
    def ws_live(ws):  # noqa: ANN001 -- flask_sock supplies this
        client_q = _monitor.register_client()
        stop = threading.Event()

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
                if isinstance(cmd, dict) and cmd.get("action") == "reply":
                    _monitor.handle_reply_action(cmd.get("event") or {})
        except Exception:
            pass
        finally:
            stop.set()
            _monitor.unregister_client(client_q)

    return _monitor


@live_bp.route("/live")
def live_view():
    return render_template(
        "live_monitor.html",
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


@live_bp.route("/live/history")
def live_history():
    if _monitor is None:
        return jsonify([])
    return jsonify(_monitor.history_snapshot())


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

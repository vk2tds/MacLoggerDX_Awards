#!/usr/bin/env python3
"""
wsjtx_remote.py -- the "Remote" tab: a control surface for WSJT-X itself
(as opposed to live_monitor.py, which is a passive DXCC/log cross-reference
view). Reuses live_monitor's shared UDP transport and websocket broadcast
(see live_monitor.get_monitor()) rather than opening a second listener --
this module only adds the HTTP routes that turn button clicks into
outgoing WSJT-X UDP commands (FreeText / HaltTx / Configure / Reply).

WSJT-X's UDP API does not expose radio frequency control (that's the rig's
job via CAT/Hamlib) or several GUI-only actions (Tune, Enable Tx toggle,
Monitor toggle, Log QSO dialog) -- this tab can't do those.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from flask import Blueprint, jsonify, render_template, request

import live_monitor
import log_writer
import macloggerdx_bridge
import wsjtx_gui_bridge
from qso_queue import QsoQueue

log = logging.getLogger("wsjtx_remote")

remote_bp = Blueprint("remote", __name__, template_folder="templates")
_queue: Optional[QsoQueue] = None


@remote_bp.route("/remote")
def remote_view():
    monitor = live_monitor.get_monitor()
    my_call = monitor.config.my_call if monitor else ""
    return render_template("wsjtx_remote.html", my_call=my_call)


@remote_bp.route("/remote/waterfall")
def remote_waterfall_view():
    """Standalone full-page waterfall -- always visible regardless of the
    show/hide checkbox on the main Remote tab, meant for a second monitor."""
    return render_template("wsjtx_waterfall.html")


@remote_bp.route("/remote/free_text", methods=["POST"])
def remote_free_text():
    monitor = live_monitor.get_monitor()
    if monitor is None:
        return jsonify({"error": "Live monitor not initialised"}), 503
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    ok = monitor.send_free_text(text, send=bool(body.get("send")))
    return jsonify({"ok": ok})


@remote_bp.route("/remote/erase", methods=["POST"])
def remote_erase():
    monitor = live_monitor.get_monitor()
    if monitor is None:
        return jsonify({"error": "Live monitor not initialised"}), 503
    body = request.get_json(silent=True) or {}
    ok = monitor.send_clear(window=int(body.get("window") or 0))
    return jsonify({"ok": ok})


@remote_bp.route("/remote/halt_tx", methods=["POST"])
def remote_halt_tx():
    monitor = live_monitor.get_monitor()
    if monitor is None:
        return jsonify({"error": "Live monitor not initialised"}), 503
    body = request.get_json(silent=True) or {}
    ok = monitor.send_halt_tx(auto_tx_only=bool(body.get("auto_tx_only")))
    return jsonify({"ok": ok})


@remote_bp.route("/remote/configure", methods=["POST"])
def remote_configure():
    monitor = live_monitor.get_monitor()
    if monitor is None:
        return jsonify({"error": "Live monitor not initialised"}), 503
    body = request.get_json(silent=True) or {}
    mode = (body.get("mode") or "").strip()
    if not mode:
        return jsonify({"error": "mode is required"}), 400
    try:
        ok = monitor.send_configure(
            mode=mode,
            frequency_tolerance=int(body.get("frequency_tolerance") or 10),
            submode=(body.get("submode") or None),
            fast_mode=bool(body.get("fast_mode")),
            tr_period=int(body.get("tr_period") or 15),
            rx_df=int(body.get("rx_df") or 1500),
            dx_call=body.get("dx_call") or "",
            dx_grid=body.get("dx_grid") or "",
            generate_messages=bool(body.get("generate_messages", True)),
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"bad configure parameters: {exc}"}), 400
    return jsonify({"ok": ok})


# ---------------------------------------------------------------------------
# GUI-scripting bridge (wsjtx_gui_bridge.py) -- for the handful of controls
# with no UDP equivalent at all: Enable Tx, Monitor, Decode, Tune, Stop, and
# the band/mode buttons. Only works if WSJT-X is running and this app has
# Accessibility permission; every route below surfaces that as a normal
# error response rather than a 500, since it's an expected/recoverable
# condition (not run yet, permission not granted, WSJT-X closed).
# ---------------------------------------------------------------------------

@remote_bp.route("/remote/gui/status")
def remote_gui_status():
    try:
        return jsonify({"ok": True, "checkboxes": wsjtx_gui_bridge.get_checkbox_states()})
    except wsjtx_gui_bridge.WsjtxGuiError as exc:
        return jsonify({"ok": False, "error": str(exc)})


@remote_bp.route("/remote/gui/checkbox", methods=["POST"])
def remote_gui_checkbox():
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    on = bool(body.get("on"))
    if name not in wsjtx_gui_bridge.CHECKBOXES:
        return jsonify({"ok": False, "error": f"Unknown checkbox {name!r}"}), 400

    if name in wsjtx_gui_bridge.TX_ARM_CHECKBOXES:
        # Enable Tx / Tune: arming has no UDP equivalent at all, so ON goes
        # through a real HID-level click (wsjtx_gui_bridge.arm_tx_checkbox).
        # OFF deliberately does NOT use a GUI click -- it goes through the
        # already-reliable UDP HaltTx command instead, which makes WSJT-X's
        # own code call autoButton->click()/stopTxButton->click() internally
        # (see wsjtx_gui_bridge.py's module docstring for why that matters).
        monitor = live_monitor.get_monitor()
        if on:
            try:
                value = wsjtx_gui_bridge.arm_tx_checkbox(name)
            except wsjtx_gui_bridge.WsjtxGuiError as exc:
                return jsonify({"ok": False, "error": str(exc)}), 503
            if not value:
                return jsonify({"ok": False, "error": f"Could not arm {name} -- gave up after retries", "value": False}), 502
            return jsonify({"ok": True, "value": True})
        else:
            if monitor is None:
                return jsonify({"ok": False, "error": "Live monitor not initialised"}), 503
            monitor.send_halt_tx(auto_tx_only=(name == "Enable Tx"))
            wsjtx_gui_bridge.set_cached_checkbox_state(name, False)
            if name == "Tune":
                # on_stopTxButton_clicked() (the auto_tx_only=False path)
                # also unchecks Enable Tx as a side effect -- see
                # wsjtx_gui_bridge.py's module docstring.
                wsjtx_gui_bridge.set_cached_checkbox_state("Enable Tx", False)
            return jsonify({"ok": True, "value": False})

    try:
        value = wsjtx_gui_bridge.set_checkbox(name, on)
    except wsjtx_gui_bridge.WsjtxGuiError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    return jsonify({"ok": True, "value": value})


@remote_bp.route("/remote/gui/button", methods=["POST"])
def remote_gui_button():
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    if name not in ("Stop",) + wsjtx_gui_bridge.BAND_BUTTONS + wsjtx_gui_bridge.MODE_BUTTONS:
        return jsonify({"ok": False, "error": f"Unknown button {name!r}"}), 400
    try:
        wsjtx_gui_bridge.click_button(name)
    except wsjtx_gui_bridge.WsjtxGuiError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    return jsonify({"ok": True})


@remote_bp.route("/remote/log_qso/preview")
def remote_log_qso_preview():
    """Build a QSO record from WSJT-X's current live Status, for the
    operator to review/edit before confirming -- this stands in for WSJT-X's
    own Log QSO dialog, which can't be reached remotely (see log_writer.py).
    """
    monitor = live_monitor.get_monitor()
    if monitor is None:
        return jsonify({"error": "Live monitor not initialised"}), 503
    status = monitor.wsjtx_status or {}
    dx_call = status.get("dx_call")
    if not dx_call:
        return jsonify({"error": "No current DX call known from WSJT-X yet"}), 404

    band = live_monitor.freq_to_band(status.get("dial_frequency_hz"))
    rx_df = status.get("rx_df")
    tx_freq_mhz = None
    if status.get("dial_frequency_hz") and isinstance(rx_df, int):
        tx_freq_mhz = (status["dial_frequency_hz"] + rx_df) / 1e6

    entity = None
    if monitor.dxcc_resolver is not None:
        entity = monitor.dxcc_resolver.lookup(dx_call)

    report = status.get("report") or ""

    return jsonify({
        "my_call": monitor.config.my_call,
        "my_grid": status.get("de_grid") or "",
        "call": dx_call,
        "grid": status.get("dx_grid") or "",
        "mode": status.get("mode") or "",
        "band": band or "",
        "tx_frequency_mhz": tx_freq_mhz,
        "rst_sent": report,
        "rst_received": report,
        "dxcc_country": entity.name if entity else None,
        "dxcc_id": entity.dxcc_id if entity else None,
        "cq_zone": entity.cq_zone if entity else None,
        "comments": "",
    })


@remote_bp.route("/remote/log_qso", methods=["POST"])
def remote_log_qso():
    monitor = live_monitor.get_monitor()
    if monitor is None:
        return jsonify({"error": "Live monitor not initialised"}), 503
    body = request.get_json(silent=True) or {}

    call = (body.get("call") or "").strip().upper()
    my_call = (body.get("my_call") or monitor.config.my_call or "").strip().upper()
    band = (body.get("band") or "").strip()
    mode = (body.get("mode") or "").strip()
    if not call or not my_call or not band or not mode:
        return jsonify({"error": "call, my_call, band and mode are all required"}), 400

    database_path = monitor.config.database_path
    qso_table = monitor.config.qso_table

    if not body.get("force"):
        dup = log_writer.find_possible_duplicate(
            database_path, qso_table, call, band, mode, near_epoch=time.time(),
        )
        if dup:
            return jsonify({"error": "possible_duplicate", "duplicate": dup}), 409

    try:
        tx_freq = body.get("tx_frequency_mhz")
        rec = log_writer.QsoRecord(
            my_call=my_call,
            my_grid=(body.get("my_grid") or "").strip(),
            call=call,
            grid=(body.get("grid") or "").strip(),
            mode=mode,
            band=band,
            tx_frequency_mhz=float(tx_freq) if tx_freq not in (None, "") else None,
            rst_sent=body.get("rst_sent") or "",
            rst_received=body.get("rst_received") or "",
            dxcc_country=body.get("dxcc_country") or None,
            dxcc_id=int(body["dxcc_id"]) if body.get("dxcc_id") not in (None, "") else None,
            cq_zone=body.get("cq_zone") or None,
            comments=body.get("comments") or "",
        )
        pk = log_writer.insert_qso(database_path, qso_table, rec)
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"bad QSO parameters: {exc}"}), 400
    except Exception:
        log.exception("Failed to insert QSO for %s", call)
        return jsonify({"error": "Failed to write QSO -- see server logs"}), 500

    return jsonify({"ok": True, "pk": pk})


@remote_bp.route("/remote/qso_queue", methods=["GET", "POST"])
def remote_qso_queue():
    """GET: list queued QSOs. POST: add one (built from the same preview
    fields the operator reviewed/edited in the modal) -- doesn't touch
    MacLoggerDX at all, just saves locally. Sending to MacLoggerDX is a
    separate, explicit step (see /remote/qso_queue/<id>/send) since that's
    the part that needs macOS Automation permission and should be reviewed
    once more before actually committing."""
    if request.method == "GET":
        return jsonify({"queue": _queue.load()})

    monitor = live_monitor.get_monitor()
    body = request.get_json(silent=True) or {}
    call = (body.get("call") or "").strip().upper()
    my_call = (body.get("my_call") or (monitor.config.my_call if monitor else "") or "").strip().upper()
    band = (body.get("band") or "").strip()
    mode = (body.get("mode") or "").strip()
    if not call or not my_call or not band or not mode:
        return jsonify({"error": "call, my_call, band and mode are all required"}), 400

    try:
        tx_freq = body.get("tx_frequency_mhz")
        entry = _queue.add({
            "my_call": my_call,
            "my_grid": (body.get("my_grid") or "").strip(),
            "call": call,
            "grid": (body.get("grid") or "").strip(),
            "mode": mode,
            "band": band,
            "tx_frequency_mhz": float(tx_freq) if tx_freq not in (None, "") else None,
            "rst_sent": body.get("rst_sent") or "",
            "rst_received": body.get("rst_received") or "",
            "dxcc_country": body.get("dxcc_country") or None,
            "dxcc_id": int(body["dxcc_id"]) if body.get("dxcc_id") not in (None, "") else None,
            "cq_zone": body.get("cq_zone") or None,
            "qso_start": time.time(),
            "qso_done": time.time(),
            "comments": body.get("comments") or "",
        })
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"bad QSO parameters: {exc}"}), 400
    return jsonify({"queue": _queue.load(), "added": entry})


def _send_one(entry_id: int, force: bool = False) -> dict:
    """Shared by the single-entry route and send-all: build ADIF for one
    queued entry and push it via macloggerdx_bridge, updating the queue's
    status either way."""
    entry = _queue.get(entry_id)
    if entry is None:
        return {"id": entry_id, "ok": False, "message": "No such queued QSO"}

    if not force:
        monitor = live_monitor.get_monitor()
        if monitor is not None:
            dup = log_writer.find_possible_duplicate(
                monitor.config.database_path, monitor.config.qso_table,
                entry["call"], entry["band"], entry["mode"], near_epoch=time.time(),
            )
            if dup:
                return {"id": entry_id, "ok": False, "error": "possible_duplicate", "duplicate": dup}

    adif = macloggerdx_bridge.build_adif_record(entry)
    ok, message = macloggerdx_bridge.send_adif_to_macloggerdx(adif)
    if ok:
        _queue.mark_sent(entry_id)
    else:
        _queue.mark_error(entry_id, message)
    return {"id": entry_id, "ok": ok, "message": message}


@remote_bp.route("/remote/qso_queue/<int:entry_id>/send", methods=["POST"])
def remote_qso_queue_send(entry_id):
    """Actually push one queued QSO into MacLoggerDX via importADIF. Meant
    to be run from the Mac MacLoggerDX is on -- the AppleScript call only
    works locally, and the first run needs a human to approve macOS's
    Automation permission prompt."""
    force = bool((request.get_json(silent=True) or {}).get("force"))
    result = _send_one(entry_id, force=force)
    status = 404 if result.get("message") == "No such queued QSO" else (
        409 if result.get("error") == "possible_duplicate" else 200
    )
    return jsonify(result), status


@remote_bp.route("/remote/qso_queue/send_all", methods=["POST"])
def remote_qso_queue_send_all():
    """Send every pending entry, one at a time (never concurrently -- two
    overlapping osascript/importADIF calls at once is asking for trouble).
    Duplicate-protected sends only; entries that hit a duplicate warning are
    left pending for the operator to review individually rather than force
    them through in a batch."""
    results = [_send_one(entry_id, force=False) for entry_id in _queue.pending_ids()]
    return jsonify({"results": results, "queue": _queue.load()})


@remote_bp.route("/remote/qso_queue/<int:entry_id>/delete", methods=["POST"])
def remote_qso_queue_delete(entry_id):
    return jsonify({"queue": _queue.delete(entry_id)})


@remote_bp.route("/remote/qso_queue/clear_sent", methods=["POST"])
def remote_qso_queue_clear_sent():
    return jsonify({"queue": _queue.clear_sent()})


def init_wsjtx_remote(app, qso_queue_path: str = "qso_queue.json"):
    """Register the /remote routes. Call after init_live_monitor() so
    live_monitor.get_monitor() has something to return."""
    global _queue
    _queue = QsoQueue(qso_queue_path)
    app.register_blueprint(remote_bp)

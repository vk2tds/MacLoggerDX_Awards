#!/usr/bin/env python3
"""
rigdial.py -- the "RigDial" tab: Flask wiring for a Contour ShuttleXpress
USB HID controller (5 buttons + jog wheel + shuttle ring), used as a
hardware remote for the rig via radio_control.py's rigctld connection. All
the actual device reading and action dispatch lives in rigdial_bridge.py
(no Flask import there) -- this module only exposes it over HTTP, same
split as wsjtx_gui_bridge.py / wsjtx_remote.py.

Frequency presets are usable from the GUI alone (POST .../apply calls
radio_control directly) -- the dial itself is optional convenience, not a
requirement for the preset picker.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, render_template, request

import radio_control
import rigdial_bridge

log = logging.getLogger("rigdial")

rigdial_bp = Blueprint("rigdial", __name__, template_folder="templates")


def init_rigdial(app, config_path: str = "rigdial_config.json", presets_path: str = "rigdial_presets.json"):
    rigdial_bridge.init_rigdial_bridge(config_path, presets_path)
    app.register_blueprint(rigdial_bp)


@rigdial_bp.route("/rigdial")
def rigdial_view():
    return render_template(
        "rigdial.html",
        button_actions=rigdial_bridge.BUTTON_ACTIONS,
        shuttle_actions=rigdial_bridge.SHUTTLE_ACTIONS,
        button_count=rigdial_bridge.BUTTON_COUNT,
    )


@rigdial_bp.route("/rigdial/status")
def rigdial_status():
    dial = rigdial_bridge.get_dial()
    if dial is None:
        return jsonify({"ok": False, "error": "RigDial not initialised"}), 503
    status = dial.status()
    status["config"] = dial.config_store.load().to_dict()
    status["presets"] = dial.preset_store.load()
    return jsonify(status)


@rigdial_bp.route("/rigdial/config", methods=["GET", "POST"])
def rigdial_config():
    dial = rigdial_bridge.get_dial()
    if dial is None:
        return jsonify({"ok": False, "error": "RigDial not initialised"}), 503

    if request.method == "GET":
        return jsonify(dial.config_store.load().to_dict())

    body = request.get_json(silent=True) or {}
    button_actions = body.get("button_actions") or {}
    for idx_str, action in button_actions.items():
        try:
            idx = int(idx_str)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": f"Invalid button index {idx_str!r}"}), 400
        if not (0 <= idx < rigdial_bridge.BUTTON_COUNT):
            return jsonify({"ok": False, "error": f"Button index {idx} out of range"}), 400
        if action not in rigdial_bridge.BUTTON_ACTIONS:
            return jsonify({"ok": False, "error": f"Unknown action {action!r}"}), 400

    shuttle_action = body.get("shuttle_action", "none")
    if shuttle_action not in rigdial_bridge.SHUTTLE_ACTIONS:
        return jsonify({"ok": False, "error": f"Unknown shuttle action {shuttle_action!r}"}), 400

    try:
        small = float(body.get("jog_step_small_hz", 10))
        big = float(body.get("jog_step_big_hz", 1000))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Jog step sizes must be numbers"}), 400
    if small <= 0 or big <= 0:
        return jsonify({"ok": False, "error": "Jog step sizes must be positive"}), 400

    cfg = rigdial_bridge.RigDialConfig(
        button_actions={str(i): button_actions.get(str(i), "none") for i in range(rigdial_bridge.BUTTON_COUNT)},
        shuttle_action=shuttle_action,
        jog_step_small_hz=small,
        jog_step_big_hz=big,
    )
    dial.config_store.save(cfg)
    return jsonify({"ok": True, "config": cfg.to_dict()})


@rigdial_bp.route("/rigdial/presets", methods=["GET", "POST"])
def rigdial_presets():
    dial = rigdial_bridge.get_dial()
    if dial is None:
        return jsonify({"ok": False, "error": "RigDial not initialised"}), 503

    if request.method == "GET":
        return jsonify({"presets": dial.preset_store.load()})

    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Name is required"}), 400
    try:
        freq_hz = float(body.get("freq_hz"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "freq_hz must be a number"}), 400
    if freq_hz <= 0:
        return jsonify({"ok": False, "error": "freq_hz must be positive"}), 400
    preset = dial.preset_store.add(name, freq_hz)
    return jsonify({"ok": True, "preset": preset})


@rigdial_bp.route("/rigdial/presets/<int:preset_id>", methods=["POST"])
def rigdial_preset_update(preset_id):
    dial = rigdial_bridge.get_dial()
    if dial is None:
        return jsonify({"ok": False, "error": "RigDial not initialised"}), 503

    body = request.get_json(silent=True) or {}
    name = body.get("name")
    freq_hz = body.get("freq_hz")
    if name is not None:
        name = str(name).strip()
        if not name:
            return jsonify({"ok": False, "error": "Name cannot be empty"}), 400
    if freq_hz is not None:
        try:
            freq_hz = float(freq_hz)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "freq_hz must be a number"}), 400
        if freq_hz <= 0:
            return jsonify({"ok": False, "error": "freq_hz must be positive"}), 400

    preset = dial.preset_store.update(preset_id, name=name, freq_hz=freq_hz)
    if preset is None:
        return jsonify({"ok": False, "error": "Preset not found"}), 404
    return jsonify({"ok": True, "preset": preset})


@rigdial_bp.route("/rigdial/presets/<int:preset_id>/delete", methods=["POST"])
def rigdial_preset_delete(preset_id):
    dial = rigdial_bridge.get_dial()
    if dial is None:
        return jsonify({"ok": False, "error": "RigDial not initialised"}), 503
    dial.preset_store.delete(preset_id)
    return jsonify({"ok": True})


@rigdial_bp.route("/rigdial/presets/<int:preset_id>/apply", methods=["POST"])
def rigdial_preset_apply(preset_id):
    dial = rigdial_bridge.get_dial()
    if dial is None:
        return jsonify({"ok": False, "error": "RigDial not initialised"}), 503
    presets = dial.preset_store.load()
    preset = next((p for p in presets if p["id"] == preset_id), None)
    if preset is None:
        return jsonify({"ok": False, "error": "Preset not found"}), 404

    client = radio_control.get_client()
    if client is None:
        return jsonify({"ok": False, "error": "Radio control not initialised"}), 503
    try:
        client.set_freq(preset["freq_hz"])
    except (radio_control.RigctldError, radio_control.RigctldConnectionError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    return jsonify({"ok": True, "freq_hz": preset["freq_hz"]})

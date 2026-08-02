#!/usr/bin/env python3
"""
frequencies.py -- the "Frequencies" tab: a shared list of named frequency
presets, editable from one place instead of being buried inside RigDial.

The presets themselves still live in rigdial_bridge.RigDialPresetStore (same
rigdial_presets.json file, same store instance via rigdial_bridge.get_dial())
-- this module doesn't own the data, just exposes it under its own tab/routes
now that it's meant to be shared across features, not RigDial-specific.

Each preset carries four boolean flags -- remote/find/radio/rigdial -- marking
which tabs it applies to. Only RigDial's own band_up/band_down/cycle_presets
actions actually read theirs so far (see rigdial_bridge.RigDial._cycle_preset).
The other three are reserved for when Remote and Find (DX Monitor) move away
from driving WSJT-X's own band buttons to select frequency, per the user's
explicit "not yet" when this was built -- they're just persisted for now.

Requires rigdial_bridge.init_rigdial_bridge() to have run first (app.py calls
rigdial.init_rigdial() before init_frequencies()).
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, render_template, request

import radio_control
import rigdial_bridge

log = logging.getLogger("frequencies")

frequencies_bp = Blueprint("frequencies", __name__, template_folder="templates")


def init_frequencies(app):
    app.register_blueprint(frequencies_bp)


def _preset_store():
    dial = rigdial_bridge.get_dial()
    return dial.preset_store if dial else None


@frequencies_bp.route("/frequencies")
def frequencies_view():
    return render_template("frequencies.html")


@frequencies_bp.route("/frequencies/presets", methods=["GET", "POST"])
def frequencies_presets():
    store = _preset_store()
    if store is None:
        return jsonify({"ok": False, "error": "RigDial bridge not initialised"}), 503

    if request.method == "GET":
        return jsonify({"presets": store.load()})

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
    preset = store.add(name, freq_hz)
    return jsonify({"ok": True, "preset": preset})


@frequencies_bp.route("/frequencies/presets/<int:preset_id>", methods=["POST"])
def frequencies_preset_update(preset_id):
    store = _preset_store()
    if store is None:
        return jsonify({"ok": False, "error": "RigDial bridge not initialised"}), 503

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

    used_by = {}
    for key in ("remote", "find", "radio", "rigdial"):
        if key in body:
            used_by[key] = bool(body[key])

    preset = store.update(preset_id, name=name, freq_hz=freq_hz, **used_by)
    if preset is None:
        return jsonify({"ok": False, "error": "Preset not found"}), 404
    return jsonify({"ok": True, "preset": preset})


@frequencies_bp.route("/frequencies/presets/<int:preset_id>/delete", methods=["POST"])
def frequencies_preset_delete(preset_id):
    store = _preset_store()
    if store is None:
        return jsonify({"ok": False, "error": "RigDial bridge not initialised"}), 503
    store.delete(preset_id)
    return jsonify({"ok": True})


@frequencies_bp.route("/frequencies/presets/<int:preset_id>/apply", methods=["POST"])
def frequencies_preset_apply(preset_id):
    store = _preset_store()
    if store is None:
        return jsonify({"ok": False, "error": "RigDial bridge not initialised"}), 503
    presets = store.load()
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

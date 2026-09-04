#!/usr/bin/env python3
"""
rigdial.py -- the "RigDial" tab: Flask wiring for a Contour ShuttleXpress
USB HID controller (5 buttons + jog wheel + shuttle ring), used as a
hardware remote for the rig via radio_control.py's rigctld connection. All
the actual device reading and action dispatch lives in rigdial_bridge.py
(no Flask import there) -- this module only exposes it over HTTP, same
split as wsjtx_gui_bridge.py / wsjtx_remote.py.

Frequency presets used to live on this tab; they moved to their own
Frequencies tab (frequencies.py) since they're meant to be shared across
Remote/Find/Radio/RigDial, not RigDial-specific -- this module still owns
the underlying store (rigdial_bridge.RigDialPresetStore, via get_dial()),
since band_up/band_down/cycle_presets still read from it.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, render_template, request

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
        shuttle_actions=rigdial_bridge.SHUTTLE_ACTIONS,
    )


@rigdial_bp.route("/rigdial/widget")
def rigdial_widget():
    """Dashboard widget: the whole RigDial screen, unsplit -- see
    templates/rigdial_widget.html and dashboard.py's module docstring for
    the overall widget pattern. Unlike the multi-section pages, this one
    has no sub-widgets to switch between (see the user's original widget
    list), so there's no data-widget-mode/CSS-hiding here."""
    return render_template(
        "rigdial_widget.html",
        shuttle_actions=rigdial_bridge.SHUTTLE_ACTIONS,
    )


@rigdial_bp.route("/rigdial/meta")
def rigdial_meta():
    """Static button-action/count constants for static/rigdial.js -- the
    full page and standalone widget route get these via Jinja globals in an
    inline <script> (see rigdial_view()/rigdial_widget() above), but a
    shadow-DOM-mounted Dashboard applet never runs that <script> at all
    (dashboard.html's mountApplet() deliberately skips <script> elements
    when moving fetched markup into a shadow root), so mountRigDial() fetches
    this instead of relying on window globals -- works identically either
    way since the values themselves never change at runtime."""
    return jsonify({
        "button_actions": rigdial_bridge.BUTTON_ACTIONS,
        "shuttle_actions": rigdial_bridge.SHUTTLE_ACTIONS,
        "button_count": rigdial_bridge.BUTTON_COUNT,
    })


@rigdial_bp.route("/rigdial/status")
def rigdial_status():
    dial = rigdial_bridge.get_dial()
    if dial is None:
        return jsonify({"ok": False, "error": "RigDial not initialised"}), 503
    status = dial.status()
    status["config"] = dial.config_store.load().to_dict()
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

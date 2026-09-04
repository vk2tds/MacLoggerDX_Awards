#!/usr/bin/env python3
"""
dashboard.py -- the "Dashboard" tab: a drag/resize board of widgets pulled
from other pages, for running this app on a big screen. Each widget is a
small dedicated page (see e.g. app.py's /dxcc/widget/* routes,
live_monitor.py's /live/entities/widget/* routes, logbook.py's
/logbook/widget/* routes) embedded in an <iframe> -- this module doesn't
know anything about what's *inside* a widget, it only arranges them.

Deliberately iframes, not a shared-JS-component system: each widget reuses
its full page's existing route/template/JS almost unchanged (lowest risk to
a lot of already-live-tested code), fully isolated from every other widget
(one erroring can't take down the board), at the cost of each widget opening
its own /live/ws connection -- a non-issue at this app's single-user, LAN
scale. May move to a shared-component version later, piecemeal, per the
user's own explicit framing when this was built.

Grid/drag/resize itself is GridStack.js (MIT, vendored in
static/vendor/gridstack/, no CDN at runtime) -- its own save()/load() format
(a list of {id, x, y, w, h, ...}) is what gets persisted here almost as-is.

WIDGET_CATALOG is the list of what's available to add to a board. Adding a
new widget later (once its own /widget/... route exists somewhere) is just
one more entry here -- no framework change needed.
"""

from __future__ import annotations

import json
import logging

from flask import Blueprint, jsonify, render_template, request

log = logging.getLogger("dashboard")

dashboard_bp = Blueprint("dashboard", __name__, template_folder="templates")

# (id, display name, iframe src, default grid width, default grid height)
# -- w/h are in GridStack's default 12-column units. First slice only (see
# the dashboard plan) -- the rest of the pages' widgets follow the same
# per-page /widget/... route pattern and just get appended here later.
WIDGET_CATALOG = [
    {"id": "dxcc_stats", "name": "DXCC: Status Box", "src": "/dxcc/widget/stats", "w": 4, "h": 3},
    {"id": "dxcc_legend", "name": "DXCC: Legend", "src": "/dxcc/widget/legend", "w": 5, "h": 3},
    {"id": "dxcc_grid", "name": "DXCC: Challenge Grid", "src": "/dxcc/widget/grid", "w": 8, "h": 8},
    {"id": "dxm_find", "name": "DX Monitor: Find + Toolbar", "src": "/live/entities/widget/find", "w": 8, "h": 5},
    {"id": "dxm_list", "name": "DX Monitor: DXCC's", "src": "/live/entities/widget/list", "w": 8, "h": 9},
    {"id": "logbook_recent", "name": "Logbook: Recent QSOs", "src": "/logbook/widget/recent", "w": 8, "h": 7},
    {"id": "logbook_confirm", "name": "Logbook: Confirmations", "src": "/logbook/widget/confirmations", "w": 8, "h": 7},
    {"id": "live_selection", "name": "Live Monitor: Selection", "src": "/live/widget/selection", "w": 8, "h": 4},
    {"id": "live_cq", "name": "Live Monitor: CQ's", "src": "/live/widget/cq", "w": 6, "h": 9},
    {"id": "live_noncq", "name": "Live Monitor: Non-CQ's", "src": "/live/widget/noncq", "w": 6, "h": 9},
    {"id": "live_merged", "name": "Live Monitor: CQ's + Non-CQ's (merged)", "src": "/live/widget/merged", "w": 12, "h": 9},
    {"id": "qsl_helper", "name": "QSL Helper: Screen", "src": "/qsl/widget", "w": 10, "h": 10},
    {"id": "remote_band_activity", "name": "Remote: Band Activity", "src": "/remote/widget/band_activity", "w": 6, "h": 8},
    {"id": "remote_rx_freq", "name": "Remote: Rx Frequency", "src": "/remote/widget/rx_freq", "w": 6, "h": 8},
    {"id": "remote_waterfall", "name": "Remote: Waterfall", "src": "/remote/widget/waterfall", "w": 8, "h": 6},
    {"id": "remote_rest", "name": "Remote: Controls", "src": "/remote/widget/rest", "w": 10, "h": 10},
    {"id": "radio_control", "name": "Radio: Control", "src": "/radio/widget/control", "w": 6, "h": 9},
    {"id": "radio_proc", "name": "Radio: rigctld", "src": "/radio/widget/proc", "w": 6, "h": 9},
    {"id": "radio_freq", "name": "Radio: Frequency", "src": "/radio/widget/freq", "w": 5, "h": 4},
    {"id": "rigdial", "name": "RigDial: Box + Status", "src": "/rigdial/widget", "w": 8, "h": 8},
    {"id": "frequencies", "name": "Frequencies: Box", "src": "/frequencies/widget", "w": 9, "h": 7},
    {"id": "help", "name": "Help: Box", "src": "/help/widget", "w": 9, "h": 9},
    {"id": "utc_clock", "name": "UTC Clock + Date", "src": "/clock/widget", "w": 6, "h": 3},
]

_LAYOUTS_FILE = "dashboard_layouts.json"
_layouts: dict = {}


def _load_layouts():
    try:
        with open(_LAYOUTS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return
    if isinstance(saved, dict):
        _layouts.update(saved)


def _save_layouts():
    try:
        with open(_LAYOUTS_FILE, "w", encoding="utf-8") as f:
            json.dump(_layouts, f, indent=2)
    except OSError:
        log.warning("Could not save %s", _LAYOUTS_FILE, exc_info=True)


_load_layouts()


def init_dashboard(app):
    app.register_blueprint(dashboard_bp)


@dashboard_bp.route("/dashboard")
def dashboard_view():
    return render_template("dashboard.html", catalog=WIDGET_CATALOG)


@dashboard_bp.route("/dashboard/layouts")
def dashboard_layouts_list():
    return jsonify({"names": sorted(_layouts.keys())})


@dashboard_bp.route("/dashboard/layouts/<name>", methods=["GET", "POST", "DELETE"])
def dashboard_layout(name):
    if request.method == "GET":
        if name not in _layouts:
            return jsonify({"ok": False, "error": "No layout named %r" % name}), 404
        return jsonify({"ok": True, "items": _layouts[name]})

    if request.method == "DELETE":
        _layouts.pop(name, None)
        _save_layouts()
        return jsonify({"ok": True})

    body = request.get_json(silent=True) or {}
    items = body.get("items")
    if not isinstance(items, list):
        return jsonify({"ok": False, "error": "items must be a list"}), 400
    _layouts[name] = items
    _save_layouts()
    return jsonify({"ok": True})

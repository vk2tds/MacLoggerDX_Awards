#!/usr/local/python3

# This code was developed for MacOS but should work under Windows and Linux

# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
# You should have received a copy of the GNU General Public License along with this program. If not,
# see <https://www.gnu.org/licenses/>.

# Having said that, it would be great to know if this software gets used. If you want, buy me a coffee, or send me some hardware
# Darryl Smith, VK2TDS. darryl@radio-active.net.au Copyright 2023

# Web app replacing the PyQt6 GUI (qtAwards.py) and the http.server prototype
# (runhello.py): a hierarchy view of every tracked award plus the DXCC Challenge
# grid with QSL/OQRS/Bureau tracking overlay.

import datetime
import logging

from flask import Flask, render_template, redirect, url_for, flash
from flask_sock import Sock

import macloggerdx_awards
import awards_tree
import dxcc_challenge
import live_monitor
import qsl_helper
import radio_control
import rigdial
import wsjtx_remote

log = logging.getLogger("app." + __name__)

APP_VERSION = "2026.07.14"

app = Flask(__name__)
app.secret_key = 'macloggerdx-awards'
sock = Sock(app)


@app.context_processor
def inject_version():
    return {'app_version': APP_VERSION}

analysis = macloggerdx_awards.analysis

state = {'last_refreshed': None, 'error': None}


def refresh():
    try:
        analysis.start()
        state['error'] = None
    except Exception as exc:
        log.exception('Failed to refresh awards from the database')
        state['error'] = str(exc)
    state['last_refreshed'] = datetime.datetime.utcnow()


refresh()

live_monitor.init_live_monitor(app, sock, live_monitor.LiveMonitorConfig(
    database_path=analysis.database_name,
    qso_table=analysis.qso_table,
    dxcc_file=analysis.dxcc_file,
    my_call="VK2TDS",
    udp_host="127.0.0.1",
    udp_port=2237,
    multicast_group="224.0.0.1",
))

qsl_helper.init_qsl_helper(app, qsl_helper.QslHelperConfig(
    database_path=analysis.database_name,
    qso_table=analysis.qso_table,
    dxcc_file=analysis.dxcc_file,
    my_calls=("VK2TDS", "AX2TDS"),
    alltxt_path="/Users/darryl/Library/Application Support/WSJT-X/ALL.TXT",
))

wsjtx_remote.init_wsjtx_remote(app)

radio_control.init_radio_control(app, radio_control.RigctldConfig(
    host="127.0.0.1",
    port=4532,
))

rigdial.init_rigdial(app)


@app.route('/')
def index():
    return redirect(url_for('awards_view'))


@app.route('/awards')
def awards_view():
    if state['error']:
        return render_template('error.html', error=state['error'])
    tree = awards_tree.build_tree(analysis.awards)
    return render_template('hierarchy.html', tree=tree, last_refreshed=state['last_refreshed'])


@app.route('/dxcc')
def dxcc_view():
    if state['error']:
        return render_template('error.html', error=state['error'])
    challenge = dxcc_challenge.build_challenge(analysis.rawtable)
    return render_template('dxcc.html', challenge=challenge, last_refreshed=state['last_refreshed'])


@app.route('/help')
def help_view():
    return render_template('help.html')


@app.route('/refresh', methods=['POST'])
def refresh_view():
    refresh()
    if state['error']:
        flash('Refresh failed: %s' % state['error'])
    else:
        flash('Awards data refreshed.')
    return redirect(url_for('awards_view'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5050, threaded=True)

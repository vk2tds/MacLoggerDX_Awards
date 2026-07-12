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

import macloggerdx_awards
import awards_tree
import dxcc_challenge

log = logging.getLogger("app." + __name__)

app = Flask(__name__)
app.secret_key = 'macloggerdx-awards'

analysis = macloggerdx_awards.analysis

state = {'last_refreshed': None, 'error': None}


def refresh():
    try:
        analysis.start()
        state['error'] = None
    except Exception as exc:
        log.exception('Failed to refresh awards from the database')
        state['error'] = str(exc)
    state['last_refreshed'] = datetime.datetime.now()


refresh()


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


@app.route('/refresh', methods=['POST'])
def refresh_view():
    refresh()
    if state['error']:
        flash('Refresh failed: %s' % state['error'])
    else:
        flash('Awards data refreshed.')
    return redirect(url_for('awards_view'))


if __name__ == '__main__':
    app.run(debug=True, port=5050)

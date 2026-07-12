#!/usr/local/python3

# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
# You should have received a copy of the GNU General Public License along with this program. If not,
# see <https://www.gnu.org/licenses/>.

# Darryl Smith, VK2TDS. darryl@radio-active.net.au Copyright 2023

# DXCC Challenge grid engine: colours each country/band cell of the ARRL DXCC Challenge
# table by confirmation status, overlays the manually tracked QSL/OQRS/Bureau requests
# from qsl_tracking.json, and reports tracked entries that are stale (already confirmed,
# or no longer match an outstanding cell) so they can be pruned.

import json
import datetime
import logging
from enum import Enum

log = logging.getLogger("app." + __name__)

STATIC_BANDS = ['160M', '80M', '40M', '30M', '20M', '17M', '15M', '12M', '10M', '6M']

QSL_TRACKING_FILE = 'qsl_tracking.json'


class Status(Enum):
    # http://colorbrewer2.org/#type=diverging&scheme=RdBu&n=11
    NULL = ('#e0e0e0', 'Blank')
    LOTW = ('#b8e186', 'LoTW')
    QSL_NONE = ('#f1b6da', 'No QSL')
    QSL_OUTBOX = ('#92c5de', 'QSL Outbox')
    QSL_CARD = ('#d1e5f0', 'Have Card')
    QSL_SENT = ('#f4a582', 'QSL Sent')
    BUREAU_SENT = ('#f7f7f7', 'Bureau Sent')
    BUREAU_OUTBOX = ('#b2182b', 'Bureau Outbox')
    OQRS_SENT = ('#fddbc7', 'OQRS Sent')
    OQRS_OUTBOX = ('#d6604d', 'OQRS Outbox')

    def __init__(self, color, label):
        self.color = color
        self.label = label


_TRACKED_STATUS = {
    ('Bureau', 'Sent'): Status.BUREAU_SENT,
    ('Bureau', 'Outbox'): Status.BUREAU_OUTBOX,
    ('OQRS', 'Sent'): Status.OQRS_SENT,
    ('OQRS', 'Outbox'): Status.OQRS_OUTBOX,
    ('QSL', 'Sent'): Status.QSL_SENT,
    ('QSL', 'Outbox'): Status.QSL_OUTBOX,
}


def load_tracking():
    with open(QSL_TRACKING_FILE, 'r') as f:
        return json.load(f)


def _cell_status_and_tooltip(value, country, band, tracking):
    """Mirrors the historical challengeTableCell()/TableModel logic: decide the
    background status for a DXCC/band cell and build its tooltip."""
    if value == '-' or value is None:
        return Status.NULL, '', ''

    first_line = value.split('\r\n', 1)[0]
    lotw, card, qso = first_line.split('/', 2)
    text = '%s/%s' % (lotw, qso)

    tooltip = ''
    if int(card) > 0:
        tooltip += '<div style="color:green;">Cards: %s</div>' % card

    if int(card) > 0 and int(lotw) == 0:
        return Status.QSL_CARD, text, tooltip

    if int(lotw) == 0:
        status = Status.QSL_NONE
        for entry in tracking:
            if entry['country'] == country and entry['band'] == band:
                s = _TRACKED_STATUS.get((entry['type'], entry['subtype']))
                if s is not None:
                    status = s

        pending_html = ''
        for line in value.split('\r\n')[1:]:
            if ',' not in line:
                continue
            call, when, last_lotw = line.split(',', 2)
            when_epoch = int(when.split('.', 1)[0])
            dt = datetime.datetime.fromtimestamp(when_epoch)
            age = datetime.datetime.now() - dt
            color = 'green' if age.days < 14 else 'orange' if age.days < 28 else 'red' if age.days < 90 else 'black'
            last = last_lotw if last_lotw else 'NEVER'
            pending_html += '<div style="color:%s;">%s %s %s</div>' % (
                color, str(dt).replace(' ', '&nbsp;'), call, last)
        if pending_html:
            tooltip = pending_html

        return status, text, tooltip

    return Status.LOTW, text, tooltip


class TrackingAudit:
    """Flags qsl_tracking.json entries that no longer need tracking: either the
    award is already confirmed (Excess) or the entry never matched an outstanding
    cell at all (stale/typo'd country or band)."""

    def __init__(self, tracking):
        self.entries = [{'details': d, 'processed': False, 'excess': False} for d in tracking]

    def observe(self, country, band, status):
        for e in self.entries:
            d = e['details']
            if d['country'] == country and d['band'] == band:
                if status in (Status.LOTW, Status.QSL_CARD):
                    e['processed'] = True
                    e['excess'] = True
                elif status in _TRACKED_STATUS.values():
                    e['processed'] = True

    def stale_entries(self):
        return [e['details'] for e in self.entries if not e['processed'] or e['excess']]


def build_challenge(rawtable):
    """rawtable is macloggerdx_awards.analysis.rawtable: a header row followed by
    one row per confirmed-or-partial DXCC entity, each cell 'LoTW/Card/QSO' or '-'."""
    tracking = load_tracking()
    audit = TrackingAudit(tracking)

    header_row, *rows = rawtable
    headers = [h.split('\r\n')[0] for h in header_row]

    categories = {}
    dxcc_count = 0
    dxcc_count_unconfirmed = 0
    challenge_count = 0
    challenge_count_unconfirmed = 0

    grid_rows = []
    for row in rows:
        country = row[0]
        cells = []
        has_dxcc = False
        has_dxcc_unconfirmed = False
        for i, value in enumerate(row[1:], start=1):
            band = STATIC_BANDS[i - 1]
            status, text, tooltip = _cell_status_and_tooltip(value, country, band, tracking)
            categories[status.name] = categories.get(status.name, 0) + 1
            audit.observe(country, band, status)

            if status in (Status.LOTW, Status.QSL_CARD):
                has_dxcc = True
                challenge_count += 1
            if status != Status.NULL:
                has_dxcc_unconfirmed = True
                challenge_count_unconfirmed += 1

            cells.append({'text': text, 'status': status, 'tooltip': tooltip})
        if has_dxcc:
            dxcc_count += 1
        if has_dxcc_unconfirmed:
            dxcc_count_unconfirmed += 1
        grid_rows.append({'country': country, 'cells': cells})

    return {
        'headers': headers[1:],
        'rows': grid_rows,
        'legend': list(Status),
        'categories': categories,
        'stats': {
            'dxcc_confirmed': dxcc_count,
            'dxcc_with_unconfirmed': dxcc_count_unconfirmed,
            'challenge_confirmed': challenge_count,
            'challenge_with_unconfirmed': challenge_count_unconfirmed,
        },
        'stale_tracking': audit.stale_entries(),
    }

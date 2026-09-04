"""Persistent log of decoded callsigns that failed to resolve to a DXCC entity.

Keyed by callsign (not an ever-growing flat list) so repeat noise/decodes of
the same call just bump count/last_seen instead of piling up duplicate rows.
"""
import json
import os
import threading
from datetime import datetime, timezone

LOG_PATH = os.path.join(os.path.dirname(__file__), 'unknown_dxcc_log.json')

_lock = threading.Lock()


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _load():
    if not os.path.exists(LOG_PATH):
        return {}
    try:
        with open(LOG_PATH, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data):
    tmp_path = LOG_PATH + '.tmp'
    with open(tmp_path, 'w') as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp_path, LOG_PATH)


def record(call, band=None, mode=None, message=None):
    """Record (or bump) an unresolved-DXCC decode for `call`."""
    if not call:
        return
    with _lock:
        data = _load()
        now = _now_iso()
        entry = data.get(call)
        if entry is None:
            entry = {
                'call': call,
                'first_seen': now,
                'last_seen': now,
                'count': 0,
                'band': band,
                'mode': mode,
                'message': message,
            }
        entry['last_seen'] = now
        entry['count'] = entry.get('count', 0) + 1
        entry['band'] = band
        entry['mode'] = mode
        entry['message'] = message
        data[call] = entry
        _save(data)


def list_entries():
    """Return all entries, most-recently-seen first."""
    with _lock:
        data = _load()
    return sorted(data.values(), key=lambda e: e.get('last_seen', ''), reverse=True)


def clear_entry(call):
    with _lock:
        data = _load()
        if call in data:
            del data[call]
            _save(data)

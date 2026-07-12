# MacLoggerDX_Awards
Award progress for MacLoggerDX

A small Flask web app that reads a MacLoggerDX SQLite log and shows:

- **Award Statuses** (`/awards`) — a collapsible tree of every tracked award
  (ARRL DXCC, CQ WAZ/WPX, NZART, RSGB, WIA) with progress badges.
- **DXCC Status** (`/dxcc`) — the ARRL DXCC Challenge grid, colour-coded by
  confirmation status, overlaid with the manually tracked QSL/OQRS/Bureau
  requests from `qsl_tracking.json`, plus a report of tracking entries that
  are stale (already confirmed, or no longer match an outstanding cell).

## Running

```
pip install -r requirements.txt
python3 app.py
```

Then open http://127.0.0.1:5050. Use the Refresh button to re-run the
analysis against the database without restarting the server.

## Configuration

- `macloggerdx_awards.py` — set `database_name` and `qso_table` in the
  `analysis` class to match your MacLoggerDX install.
- `qsl_tracking.json` — your manually tracked outstanding QSL/OQRS/Bureau
  requests (type, subtype, country, band, call, notes). Edit this directly;
  the DXCC Status page will flag entries that are now stale so you can prune
  them.

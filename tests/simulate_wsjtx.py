#!/usr/bin/env python3
"""
simulate_wsjtx.py -- Send fake WSJT-X UDP traffic to 127.0.0.1:2237 so you
can exercise live_monitor.py end-to-end (Flask app, websocket, browser
table) WITHOUT needing WSJT-X, a radio, or even MacLoggerDX running.

Usage:
    python3 simulate_wsjtx.py                     # send one heartbeat, one
                                                    # status, then a scripted
                                                    # sequence of decodes
    python3 simulate_wsjtx.py --loop               # repeat forever, ~ every 15s
                                                    # (mimics one FT8 cycle)
    python3 simulate_wsjtx.py --port 2237 --host 127.0.0.1

What to expect in the browser (http://127.0.0.1:5050/live):
    - The status line updates from the Status packet (dial frequency/mode).
    - A "CQ VK2ABC QF56" row appears (adjust VK2ABC to a call you know is/
      isn't in your log to see the NEW DXCC / WKD / CFM tags react).
    - A "CQ 6 W6XYZ CM87" row appears dimmed/struck-through if your
      configured "My call" area digit isn't 6.
    - An RR73 exchange row appears with no special tags.

This intentionally mirrors the same wire format wsjtx_udp.py parses, using
its own build_* encoders -- so this script is also a decent regression
check that the encoder and decoder halves of wsjtx_udp.py agree with each
other (see test_wsjtx_udp.py for the same thing as unit tests).
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wsjtx_udp as w


SCRIPT = [
    # (delay_seconds, message)
    (0.0, "CQ VK2ABC QF56"),
    (2.0, "CQ DX JA1XYZ PM95"),
    (2.0, "CQ 6 W6ABC CM87"),        # directed CQ, call-area 6 -- watch the dimming toggle
    (2.0, "VK2ABC W1AW FN31"),
    (2.0, "W1AW VK2ABC -14"),
    (2.0, "VK2ABC W1AW R-09"),
    (2.0, "W1AW VK2ABC RR73"),
    (2.0, "CQ POTA G4XYZ IO91"),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2237)
    ap.add_argument("--loop", action="store_true", help="repeat the script forever")
    ap.add_argument("--mode", default="FT8")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    addr = (args.host, args.port)

    def send(data: bytes, label: str):
        sock.sendto(data, addr)
        print(f"sent {label} -> {addr}")

    send(w.build_heartbeat(version="SIMULATOR", revision="0"), "Heartbeat")
    send(w.build_status(dial_frequency_hz=14074000, mode=args.mode, de_call="VK2TDS", de_grid="QF56", decoding=True), "Status")

    while True:
        for delay, message in SCRIPT:
            time.sleep(delay)
            data = w.build_decode(
                time_ms=int((time.time() % 86400) * 1000),
                snr=-10,
                mode=args.mode,
                message=message,
            )
            send(data, f"Decode({message!r})")
        if not args.loop:
            break
        time.sleep(3.0)

    print("Done. Re-run with --loop to keep sending, or Ctrl+C an already-looping run.")


if __name__ == "__main__":
    main()

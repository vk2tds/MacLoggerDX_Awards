#!/usr/bin/env python3
"""
wsjtx_udp.py -- Minimal, defensive parser/listener for the WSJT-X "NetworkMessage"
UDP protocol (the same protocol JT-Bridge, GridTracker, JTAlert etc. use).

Reference: comments at the top of NetworkMessage.hpp in the WSJT-X source tree.
https://sourceforge.net/p/wsjt/wsjtx/ci/master/tree/NetworkMessage.hpp

Wire format summary
--------------------
Every UDP datagram is a Qt "QDataStream" blob, big-endian, with no padding:

    quint32   magic              0xadbccbda
    quint32   schema version     (1, 2 or 3 in the wild)
    quint32   message type       (see MessageType below)
    <message-type-specific fields>

Every message (after the common header) starts with:

    QString   id                 the "Unique application identifier"
                                  (WSJT-X's Settings/Reporting/"Rig name", default "WSJT-X")

Qt primitive encodings used here:
    quint8   / bool   -> 1 byte
    qint32 / quint32  -> 4 bytes, big-endian
    qint64 / quint64  -> 8 bytes, big-endian
    double            -> 8 bytes, big-endian IEEE-754
    QTime             -> quint32, milliseconds since midnight (0xFFFFFFFF = invalid/null)
    QString           -> quint32 byte-length prefix, followed by that many UTF-8 bytes.
                          A length of 0xFFFFFFFF means a null (None) string.

This module deliberately parses defensively: WSJT-X has added a handful of
trailing fields to Status/Decode/QSOLogged across schema versions 1->3, so
every decoder stops cleanly (rather than raising) as soon as it runs out of
bytes, and returns whatever fields it managed to read. That means this will
keep working even against WSJT-X versions we haven't tested against.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import socket
import struct
from typing import Any, Callable, Optional

log = logging.getLogger("wsjtx_udp")

MAGIC = 0xADBCCBDA

# NetworkMessage.hpp "enum MessageType"
MSG_HEARTBEAT = 0
MSG_STATUS = 1
MSG_DECODE = 2
MSG_CLEAR = 3
MSG_REPLY = 4
MSG_QSO_LOGGED = 5
MSG_CLOSE = 6
MSG_REPLAY = 7
MSG_HALT_TX = 8
MSG_FREE_TEXT = 9
MSG_WSPR_DECODE = 10
MSG_LOCATION = 11
MSG_LOGGED_ADIF = 12
MSG_HIGHLIGHT_CALLSIGN = 13
MSG_SWITCH_CONFIGURATION = 14
MSG_CONFIGURE = 15

MESSAGE_TYPE_NAMES = {
    MSG_HEARTBEAT: "Heartbeat",
    MSG_STATUS: "Status",
    MSG_DECODE: "Decode",
    MSG_CLEAR: "Clear",
    MSG_REPLY: "Reply",
    MSG_QSO_LOGGED: "QSOLogged",
    MSG_CLOSE: "Close",
    MSG_REPLAY: "Replay",
    MSG_HALT_TX: "HaltTx",
    MSG_FREE_TEXT: "FreeText",
    MSG_WSPR_DECODE: "WSPRDecode",
    MSG_LOCATION: "Location",
    MSG_LOGGED_ADIF: "LoggedADIF",
    MSG_HIGHLIGHT_CALLSIGN: "HighlightCallsign",
    MSG_SWITCH_CONFIGURATION: "SwitchConfiguration",
    MSG_CONFIGURE: "Configure",
}


class TruncatedMessage(Exception):
    """Raised internally when a reader runs out of bytes. Callers should
    treat this as "stop parsing, keep what you have" rather than a hard error."""


class Reader:
    """Sequential big-endian reader over a bytes buffer, matching QDataStream."""

    def __init__(self, buf: bytes):
        self.buf = buf
        self.pos = 0

    def remaining(self) -> int:
        return len(self.buf) - self.pos

    def _take(self, n: int) -> bytes:
        if self.remaining() < n:
            raise TruncatedMessage(f"wanted {n} bytes, {self.remaining()} left")
        chunk = self.buf[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def u8(self) -> int:
        return struct.unpack(">B", self._take(1))[0]

    def bool(self) -> bool:
        return self.u8() != 0

    def i32(self) -> int:
        return struct.unpack(">i", self._take(4))[0]

    def u32(self) -> int:
        return struct.unpack(">I", self._take(4))[0]

    def i64(self) -> int:
        return struct.unpack(">q", self._take(8))[0]

    def u64(self) -> int:
        return struct.unpack(">Q", self._take(8))[0]

    def f64(self) -> float:
        return struct.unpack(">d", self._take(8))[0]

    def qstring(self) -> Optional[str]:
        length = self.u32()
        if length == 0xFFFFFFFF:
            return None
        return self._take(length).decode("utf-8", errors="replace")

    def qtime_ms(self) -> Optional[int]:
        """QTime serialised as ms-since-midnight, 0xFFFFFFFF == null/invalid."""
        val = self.u32()
        if val == 0xFFFFFFFF:
            return None
        return val

    def qdate_julian(self) -> Optional[int]:
        """QDate (Qt >= 5.0 wire format) as a signed 64-bit Julian day number."""
        val = self.i64()
        return val if val != 0 else None

    def qdatetime_utc(self) -> Optional[dict]:
        """
        Best-effort QDateTime reader (QDate, QTime, quint8 timespec[, offset]).
        WSJT-X always logs in UTC (timespec == 1) so we don't bother decoding
        TimeZone (spec 3) payloads beyond skipping what we can.
        """
        julian_day = self.qdate_julian()
        ms = self.qtime_ms()
        timespec = self.u8()
        utc_offset_s = None
        if timespec == 2:  # Qt::OffsetFromUTC
            utc_offset_s = self.i32()
        elif timespec == 3:  # Qt::TimeZone - payload we don't attempt to decode
            raise TruncatedMessage("TimeZone-qualified QDateTime not supported")
        return {
            "julian_day": julian_day,
            "ms_since_midnight": ms,
            "timespec": timespec,
            "utc_offset_s": utc_offset_s,
        }


def julian_day_to_iso(julian_day: Optional[int], ms_since_midnight: Optional[int]) -> Optional[str]:
    """Convert (Julian day, ms-since-midnight) into an ISO-8601 UTC string."""
    if julian_day is None:
        return None
    import datetime as _dt
    # Julian day 0 = -4713-11-24 (proleptic Gregorian) per Qt's convention;
    # Python's date.fromordinal(1) == 0001-01-01, whose Julian day number is 1721426.
    try:
        d = _dt.date.fromordinal(julian_day - 1721425)
    except (ValueError, OverflowError):
        return None
    if ms_since_midnight is None:
        return d.isoformat()
    seconds, ms = divmod(ms_since_midnight, 1000)
    t = _dt.time(seconds // 3600 % 24, (seconds // 60) % 60, seconds % 60, ms * 1000)
    return _dt.datetime.combine(d, t).isoformat() + "Z"


@dataclasses.dataclass
class WsjtxMessage:
    type: int
    type_name: str
    id: Optional[str]
    fields: dict
    raw_len: int
    source: tuple


def parse_datagram(data: bytes, addr: tuple) -> Optional[WsjtxMessage]:
    """Parse one UDP datagram. Returns None if it isn't a recognised WSJT-X packet."""
    r = Reader(data)
    try:
        magic = r.u32()
        if magic != MAGIC:
            return None
        _schema = r.u32()
        msg_type = r.u32()
        msg_id = r.qstring()
    except TruncatedMessage:
        return None

    fields: dict[str, Any] = {}
    try:
        if msg_type == MSG_HEARTBEAT:
            fields["max_schema"] = r.u32()
            fields["version"] = r.qstring()
            fields["revision"] = r.qstring()

        elif msg_type == MSG_STATUS:
            fields["dial_frequency_hz"] = r.u64()
            fields["mode"] = r.qstring()
            fields["dx_call"] = r.qstring()
            fields["report"] = r.qstring()
            fields["tx_mode"] = r.qstring()
            fields["tx_enabled"] = r.bool()
            fields["transmitting"] = r.bool()
            fields["decoding"] = r.bool()
            fields["rx_df"] = r.u32()
            fields["tx_df"] = r.u32()
            fields["de_call"] = r.qstring()
            fields["de_grid"] = r.qstring()
            fields["dx_grid"] = r.qstring()
            fields["tx_watchdog"] = r.bool()
            fields["sub_mode"] = r.qstring()
            fields["fast_mode"] = r.bool()
            fields["special_op_mode"] = r.u8()
            fields["frequency_tolerance"] = r.u32()
            fields["tr_period"] = r.u32()
            fields["configuration_name"] = r.qstring()
            fields["tx_message"] = r.qstring()

        elif msg_type == MSG_DECODE:
            fields["is_new"] = r.bool()
            fields["time_ms"] = r.qtime_ms()
            fields["snr"] = r.i32()
            fields["delta_time_s"] = r.f64()
            fields["delta_freq_hz"] = r.u32()
            fields["mode"] = r.qstring()
            fields["message"] = r.qstring()
            fields["low_confidence"] = r.bool()
            fields["off_air"] = r.u8()

        elif msg_type == MSG_CLEAR:
            fields["window"] = r.u8()

        elif msg_type == MSG_QSO_LOGGED:
            fields["date_time_off"] = r.qdatetime_utc()
            fields["dx_call"] = r.qstring()
            fields["dx_grid"] = r.qstring()
            fields["tx_frequency_hz"] = r.u64()
            fields["mode"] = r.qstring()
            fields["report_sent"] = r.qstring()
            fields["report_received"] = r.qstring()
            fields["tx_power"] = r.qstring()
            fields["comments"] = r.qstring()
            fields["name"] = r.qstring()
            fields["date_time_on"] = r.qdatetime_utc()
            fields["operator_call"] = r.qstring()
            fields["my_call"] = r.qstring()
            fields["my_grid"] = r.qstring()
            fields["exchange_sent"] = r.qstring()
            fields["exchange_received"] = r.qstring()
            fields["adif_propagation_mode"] = r.qstring()

        elif msg_type == MSG_CLOSE:
            pass  # id only

        elif msg_type == MSG_LOGGED_ADIF:
            fields["adif_text"] = r.qstring()

        else:
            # Unhandled/legacy message type: report the type but no fields.
            pass

    except TruncatedMessage:
        # Newer/older schema than we coded for -- keep whatever fields we
        # already parsed instead of dropping the whole message.
        pass

    type_name = MESSAGE_TYPE_NAMES.get(msg_type, f"Unknown({msg_type})")
    return WsjtxMessage(
        type=msg_type,
        type_name=type_name,
        id=msg_id,
        fields=fields,
        raw_len=len(data),
        source=addr,
    )


# ---------------------------------------------------------------------------
# Outgoing messages (only the ones we need)
# ---------------------------------------------------------------------------

def _write_qstring(parts: list, s: Optional[str]):
    if s is None:
        parts.append(struct.pack(">I", 0xFFFFFFFF))
    else:
        b = s.encode("utf-8")
        parts.append(struct.pack(">I", len(b)))
        parts.append(b)


def _pack_header(parts: list, client_id: str, msg_type: int, schema: int = 2):
    parts.append(struct.pack(">I", MAGIC))
    parts.append(struct.pack(">I", schema))
    parts.append(struct.pack(">I", msg_type))
    _write_qstring(parts, client_id)


def build_heartbeat(client_id: str = "WSJT-X", max_schema: int = 2, version: str = "2.6.1", revision: str = "0") -> bytes:
    parts = []
    _pack_header(parts, client_id, MSG_HEARTBEAT)
    parts.append(struct.pack(">I", max_schema))
    _write_qstring(parts, version)
    _write_qstring(parts, revision)
    return b"".join(parts)


def build_status(
    client_id: str = "WSJT-X",
    dial_frequency_hz: int = 14074000,
    mode: str = "FT8",
    dx_call: Optional[str] = None,
    report: Optional[str] = None,
    tx_mode: str = "FT8",
    tx_enabled: bool = False,
    transmitting: bool = False,
    decoding: bool = True,
    rx_df: int = 1500,
    tx_df: int = 1500,
    de_call: str = "",
    de_grid: str = "",
    dx_grid: Optional[str] = None,
    tx_watchdog: bool = False,
    sub_mode: Optional[str] = None,
    fast_mode: bool = False,
    special_op_mode: int = 0,
    frequency_tolerance: int = 10,
    tr_period: int = 15,
    configuration_name: str = "Default",
    tx_message: str = "",
) -> bytes:
    """Build a Status (1) message -- useful for driving a fake dial
    frequency/mode into a listener during testing (see tests/simulate_wsjtx.py)."""
    parts = []
    _pack_header(parts, client_id, MSG_STATUS)
    parts.append(struct.pack(">Q", dial_frequency_hz))
    _write_qstring(parts, mode)
    _write_qstring(parts, dx_call)
    _write_qstring(parts, report)
    _write_qstring(parts, tx_mode)
    parts.append(struct.pack(">B", 1 if tx_enabled else 0))
    parts.append(struct.pack(">B", 1 if transmitting else 0))
    parts.append(struct.pack(">B", 1 if decoding else 0))
    parts.append(struct.pack(">I", rx_df))
    parts.append(struct.pack(">I", tx_df))
    _write_qstring(parts, de_call)
    _write_qstring(parts, de_grid)
    _write_qstring(parts, dx_grid)
    parts.append(struct.pack(">B", 1 if tx_watchdog else 0))
    _write_qstring(parts, sub_mode)
    parts.append(struct.pack(">B", 1 if fast_mode else 0))
    parts.append(struct.pack(">B", special_op_mode))
    parts.append(struct.pack(">I", frequency_tolerance))
    parts.append(struct.pack(">I", tr_period))
    _write_qstring(parts, configuration_name)
    _write_qstring(parts, tx_message)
    return b"".join(parts)


def build_decode(
    client_id: str = "WSJT-X",
    is_new: bool = True,
    time_ms: int = 0,
    snr: int = -10,
    delta_time_s: float = 0.2,
    delta_freq_hz: int = 1500,
    mode: str = "FT8",
    message: str = "CQ VK2ABC QF56",
    low_confidence: bool = False,
    off_air: int = 0,
) -> bytes:
    """Build a Decode (2) message -- the main one tests/simulate_wsjtx.py uses
    to feed synthetic FT8 traffic into live_monitor.py without WSJT-X."""
    parts = []
    _pack_header(parts, client_id, MSG_DECODE)
    parts.append(struct.pack(">B", 1 if is_new else 0))
    parts.append(struct.pack(">I", time_ms))
    parts.append(struct.pack(">i", snr))
    parts.append(struct.pack(">d", delta_time_s))
    parts.append(struct.pack(">I", delta_freq_hz))
    _write_qstring(parts, mode)
    _write_qstring(parts, message)
    parts.append(struct.pack(">B", 1 if low_confidence else 0))
    parts.append(struct.pack(">B", off_air))
    return b"".join(parts)


def build_highlight_callsign(
    client_id: str,
    callsign: str,
    bg_rgb: Optional[tuple],
    fg_rgb: Optional[tuple],
    highlight_last: bool = False,
) -> bytes:
    """
    Build a HighlightCallsign (13) message telling WSJT-X to colour a
    callsign in its own Band Activity / Rx Frequency windows.
    bg_rgb / fg_rgb: (r, g, b) 0-255 tuples, or None to clear highlighting.
    QColor is serialised by Qt as: quint8 spec, then 5x quint16 components
    (for Rgb spec: alpha unused=0xffff, r,g,b scaled to 16-bit, pad=0).
    """
    parts = []
    parts.append(struct.pack(">I", MAGIC))
    parts.append(struct.pack(">I", 2))  # schema
    parts.append(struct.pack(">I", MSG_HIGHLIGHT_CALLSIGN))
    _write_qstring(parts, client_id)
    _write_qstring(parts, callsign)

    def _color(rgb):
        if rgb is None:
            parts.append(struct.pack(">B", 0))  # QColor::Invalid
            return
        r, g, b = rgb
        parts.append(struct.pack(">B", 1))  # QColor::Rgb
        parts.append(struct.pack(">5H", 0xFFFF, r * 257, g * 257, b * 257, 0))

    _color(bg_rgb)
    _color(fg_rgb)
    parts.append(struct.pack(">B", 1 if highlight_last else 0))
    return b"".join(parts)


# ---------------------------------------------------------------------------
# asyncio listener
# ---------------------------------------------------------------------------

MessageHandler = Callable[[WsjtxMessage], None]


class WsjtxUdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_message: MessageHandler):
        self.on_message = on_message
        self.transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport: asyncio.BaseTransport):
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple):
        try:
            msg = parse_datagram(data, addr)
        except Exception:
            log.exception("Failed to parse WSJT-X datagram from %s", addr)
            return
        if msg is None:
            return
        try:
            self.on_message(msg)
        except Exception:
            log.exception("on_message handler raised for %s", msg.type_name)

    def error_received(self, exc: Exception):
        log.warning("WSJT-X UDP socket error: %s", exc)


async def run_listener(
    on_message: MessageHandler,
    host: str = "127.0.0.1",
    port: int = 2237,
    multicast_group: Optional[str] = None,
) -> asyncio.DatagramTransport:
    """
    Start listening for WSJT-X UDP traffic. Returns the transport so the
    caller can transport.close() to stop it.

    If multicast_group is set (e.g. "224.0.0.1", matching WSJT-X's UDP
    Server "Multicast" setting) we join that group in addition to binding.
    """
    loop = asyncio.get_running_loop()

    def _make_sock():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        # Binding to 0.0.0.0 (rather than the multicast address itself) is
        # the more portable choice across macOS/Linux when joining a
        # multicast group; plain unicast just binds to `host` as given.
        bind_addr = "0.0.0.0" if multicast_group else host
        sock.bind((bind_addr, port))
        if multicast_group:
            mreq = socket.inet_aton(multicast_group) + socket.inet_aton("0.0.0.0")
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.setblocking(False)
        return sock

    udp_sock = _make_sock()
    transport, _protocol = await loop.create_datagram_endpoint(
        lambda: WsjtxUdpProtocol(on_message),
        sock=udp_sock,
    )
    log.info("Listening for WSJT-X UDP on %s:%s%s", host, port,
              f" (multicast {multicast_group})" if multicast_group else "")
    return transport

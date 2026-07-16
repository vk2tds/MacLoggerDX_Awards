import struct
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wsjtx_udp as w


def _header(msg_type, client_id="WSJT-X", schema=2):
    parts = [struct.pack(">I", w.MAGIC), struct.pack(">I", schema), struct.pack(">I", msg_type)]
    parts.append(struct.pack(">I", len(client_id.encode())))
    parts.append(client_id.encode())
    return parts


def _qstring(s):
    if s is None:
        return struct.pack(">I", 0xFFFFFFFF)
    b = s.encode("utf-8")
    return struct.pack(">I", len(b)) + b


def test_not_wsjtx_packet_returns_none():
    assert w.parse_datagram(b"garbage", ("127.0.0.1", 1234)) is None


def test_heartbeat_roundtrip():
    parts = _header(w.MSG_HEARTBEAT)
    parts.append(struct.pack(">I", 3))
    parts.append(_qstring("2.6.1"))
    parts.append(_qstring("abcdef1"))
    data = b"".join(parts)
    msg = w.parse_datagram(data, ("127.0.0.1", 2237))
    assert msg is not None
    assert msg.type == w.MSG_HEARTBEAT
    assert msg.type_name == "Heartbeat"
    assert msg.id == "WSJT-X"
    assert msg.fields["max_schema"] == 3
    assert msg.fields["version"] == "2.6.1"
    assert msg.fields["revision"] == "abcdef1"


def test_decode_message_roundtrip():
    parts = _header(w.MSG_DECODE)
    parts.append(struct.pack(">B", 1))          # New
    parts.append(struct.pack(">I", 123456))     # Time ms since midnight
    parts.append(struct.pack(">i", -14))         # SNR
    parts.append(struct.pack(">d", 0.3))         # DeltaTime
    parts.append(struct.pack(">I", 1500))        # DeltaFrequency
    parts.append(_qstring("FT8"))
    parts.append(_qstring("CQ VK2ABC QF56"))
    parts.append(struct.pack(">B", 0))           # LowConfidence
    parts.append(struct.pack(">B", 0))           # OffAir
    data = b"".join(parts)

    msg = w.parse_datagram(data, ("127.0.0.1", 2237))
    assert msg.type_name == "Decode"
    assert msg.fields["is_new"] is True
    assert msg.fields["snr"] == -14
    assert abs(msg.fields["delta_time_s"] - 0.3) < 1e-9
    assert msg.fields["mode"] == "FT8"
    assert msg.fields["message"] == "CQ VK2ABC QF56"
    assert msg.fields["low_confidence"] is False


def test_decode_message_truncated_still_parses_partial():
    """Simulate an older WSJT-X that doesn't send the OffAir field."""
    parts = _header(w.MSG_DECODE)
    parts.append(struct.pack(">B", 1))
    parts.append(struct.pack(">I", 123456))
    parts.append(struct.pack(">i", -14))
    parts.append(struct.pack(">d", 0.3))
    parts.append(struct.pack(">I", 1500))
    parts.append(_qstring("FT8"))
    parts.append(_qstring("CQ VK2ABC QF56"))
    parts.append(struct.pack(">B", 0))  # LowConfidence, then truncate (no OffAir byte)
    data = b"".join(parts)

    msg = w.parse_datagram(data, ("127.0.0.1", 2237))
    assert msg is not None
    assert msg.fields["message"] == "CQ VK2ABC QF56"
    assert "off_air" not in msg.fields  # gracefully stopped, not a crash


def test_status_message_null_dx_call():
    parts = _header(w.MSG_STATUS)
    parts.append(struct.pack(">Q", 14074000))
    parts.append(_qstring("FT8"))
    parts.append(_qstring(None))       # DXCall null
    parts.append(_qstring(""))
    parts.append(_qstring("FT8"))
    parts.append(struct.pack(">B", 1))  # tx_enabled
    parts.append(struct.pack(">B", 0))  # transmitting
    parts.append(struct.pack(">B", 1))  # decoding
    parts.append(struct.pack(">I", 1500))
    parts.append(struct.pack(">I", 1500))
    parts.append(_qstring("VK2ABC"))
    parts.append(_qstring("QF56"))
    parts.append(_qstring(None))
    parts.append(struct.pack(">B", 0))
    parts.append(_qstring(None))
    parts.append(struct.pack(">B", 0))
    parts.append(struct.pack(">B", 0))
    parts.append(struct.pack(">I", 10))
    parts.append(struct.pack(">I", 15))
    parts.append(_qstring("Default"))
    parts.append(_qstring(""))
    data = b"".join(parts)

    msg = w.parse_datagram(data, ("127.0.0.1", 2237))
    assert msg.type_name == "Status"
    assert msg.fields["dial_frequency_hz"] == 14074000
    assert msg.fields["dx_call"] is None
    assert msg.fields["de_call"] == "VK2ABC"
    assert msg.fields["configuration_name"] == "Default"


def test_build_heartbeat_roundtrip():
    data = w.build_heartbeat(version="2.7.0", revision="deadbeef")
    msg = w.parse_datagram(data, ("127.0.0.1", 2237))
    assert msg.type_name == "Heartbeat"
    assert msg.fields["version"] == "2.7.0"
    assert msg.fields["revision"] == "deadbeef"


def test_build_status_roundtrip():
    data = w.build_status(dial_frequency_hz=7074000, mode="FT8", dx_call="W1AW", de_call="VK2ABC")
    msg = w.parse_datagram(data, ("127.0.0.1", 2237))
    assert msg.type_name == "Status"
    assert msg.fields["dial_frequency_hz"] == 7074000
    assert msg.fields["dx_call"] == "W1AW"
    assert msg.fields["de_call"] == "VK2ABC"


def test_build_decode_roundtrip():
    data = w.build_decode(message="CQ DX VK2ABC QF56", snr=-5, mode="FT8")
    msg = w.parse_datagram(data, ("127.0.0.1", 2237))
    assert msg.type_name == "Decode"
    assert msg.fields["message"] == "CQ DX VK2ABC QF56"
    assert msg.fields["snr"] == -5


def test_highlight_callsign_builds_bytes_without_error():
    data = w.build_highlight_callsign("WSJT-X", "VK2ABC", (255, 255, 0), (0, 0, 0), True)
    assert data[:4] == struct.pack(">I", w.MAGIC)
    # re-parse the header portion to confirm message type round-trips
    r = w.Reader(data)
    assert r.u32() == w.MAGIC
    assert r.u32() == 2
    assert r.u32() == w.MSG_HIGHLIGHT_CALLSIGN


def test_free_text_header_and_fields_roundtrip():
    data = w.build_free_text("WSJT-X", "TNX 73 GL", send=True)
    r = w.Reader(data)
    assert r.u32() == w.MAGIC
    r.u32()  # schema
    assert r.u32() == w.MSG_FREE_TEXT
    assert r.qstring() == "WSJT-X"
    assert r.qstring() == "TNX 73 GL"
    assert r.bool() is True


def test_halt_tx_header_and_fields_roundtrip():
    data = w.build_halt_tx("WSJT-X", auto_tx_only=True)
    r = w.Reader(data)
    assert r.u32() == w.MAGIC
    r.u32()
    assert r.u32() == w.MSG_HALT_TX
    assert r.qstring() == "WSJT-X"
    assert r.bool() is True


def test_configure_header_and_fields_roundtrip():
    data = w.build_configure(
        "WSJT-X", mode="FT4", frequency_tolerance=20, submode=None, fast_mode=True,
        tr_period=6, rx_df=1234, dx_call="VK2ABC", dx_grid="QF56", generate_messages=False,
    )
    r = w.Reader(data)
    assert r.u32() == w.MAGIC
    r.u32()
    assert r.u32() == w.MSG_CONFIGURE
    assert r.qstring() == "WSJT-X"
    assert r.qstring() == "FT4"
    assert r.u32() == 20
    assert r.qstring() is None
    assert r.bool() is True
    assert r.u32() == 6
    assert r.u32() == 1234
    assert r.qstring() == "VK2ABC"
    assert r.qstring() == "QF56"
    assert r.bool() is False

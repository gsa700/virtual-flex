"""VITA-49 discovery packet layout tests."""
import struct

from virtualflex import vita49


def _fields(pkt: bytes):
    header = struct.unpack(">I", pkt[0:4])[0]
    return {
        "pkt_type": (header >> 28) & 0xF,
        "class_present": (header >> 27) & 0x1,
        "tsi": (header >> 24) & 0x3,
        "tsf": (header >> 22) & 0x3,
        "size_words": header & 0xFFFF,
        "stream_id": struct.unpack(">I", pkt[4:8])[0],
        "class_hi": struct.unpack(">I", pkt[8:12])[0],
        "class_lo": struct.unpack(">I", pkt[12:16])[0],
    }


def test_discovery_header_with_timestamp():
    pkt = vita49.build_discovery_packet("model=FLEX-8600 serial=1-2-3-4", include_timestamp=True)
    f = _fields(pkt)
    assert f["pkt_type"] == vita49.PKT_TYPE_EXT_DATA_WITH_STREAM
    assert f["class_present"] == 1
    assert f["stream_id"] == vita49.DISCOVERY_STREAM_ID
    assert f["class_hi"] == vita49.FLEX_OUI                      # 0x00001C2D
    assert f["class_lo"] == (vita49.DISCOVERY_INFO_CLASS << 16) | vita49.DISCOVERY_PACKET_CLASS  # 0x534CFFFF
    assert f["size_words"] == len(pkt) // 4                      # size counts whole packet
    assert pkt[16:28] == b"\x00" * 12                            # zeroed timestamps
    assert len(pkt) % 4 == 0


def test_discovery_header_without_timestamp():
    pkt = vita49.build_discovery_packet("model=FLEX-8600", include_timestamp=False)
    f = _fields(pkt)
    assert f["tsi"] == 0 and f["tsf"] == 0
    # header (1) + stream (1) + class (2) = 4 words, no timestamp words; payload at byte 16
    assert pkt[16:].rstrip(b"\x00") == b"model=FLEX-8600"
    assert f["size_words"] == len(pkt) // 4


def test_payload_is_ascii_recoverable():
    payload = "model=FLEX-8600 serial=AB-CD ip=192.168.0.20 port=4992"
    pkt = vita49.build_discovery_packet(payload, include_timestamp=True)
    body = pkt[28:].rstrip(b"\x00").decode("ascii")
    assert body == payload

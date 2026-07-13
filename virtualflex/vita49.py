"""Minimal VITA-49 construction for FlexRadio discovery broadcasts.

A FlexRadio announces itself with a VITA-49 "extension data with stream" packet
whose class ID carries the FlexRadio OUI and the discovery packet-class code.
A peripheral such as the 4O3A PowerGenius XL listens for these broadcasts and
matches the ``serial=`` token against its paired radio before connecting to the
TCP command port. Only discovery needs VITA framing; the command/status channel
is plain ASCII (see :mod:`virtualflex.protocol`).

Constants verified against flexlib-go/vita (hb9fxq) and the SmartSDR API docs.
"""
from __future__ import annotations

import struct

# VITA-49 packet type (upper nibble of the header word). Discovery carries a
# stream id, so it is an "extension data with stream" packet.
PKT_TYPE_EXT_DATA_WITH_STREAM = 0x3

# FlexRadio VITA constants.
FLEX_OUI = 0x001C2D                 # FlexRadio Systems OUI (00:1C:2D)
DISCOVERY_STREAM_ID = 0x00000800
DISCOVERY_INFO_CLASS = 0x534C       # information class code — ASCII "SL"
DISCOVERY_PACKET_CLASS = 0xFFFF     # SL_VITA_DISCOVERY_CLASS

# Timestamp-integer / -fractional type codes (2 bits each in the header word).
TSI_NONE, TSI_UTC, TSI_GPS, TSI_OTHER = 0, 1, 2, 3
TSF_NONE, TSF_SAMPLE, TSF_REAL, TSF_FREE = 0, 1, 2, 3


def build_discovery_packet(
    payload: str,
    *,
    packet_count: int = 0,
    include_timestamp: bool = True,
) -> bytes:
    """Wrap an ASCII ``key=value`` payload in a FlexRadio VITA-49 discovery packet.

    ``payload`` is a space-separated token list, e.g.::

        model=FLEX-8600 serial=1234-... version=3.6.19.35 ip=192.168.0.20 port=4992

    Spaces inside a value (the nickname) must already be encoded as underscores.

    ``include_timestamp`` adds the (zeroed) integer + fractional timestamp words,
    yielding the 28-byte header a real radio emits. If a capture shows the radio
    omits them, set it False for a 16-byte header — the two TSI/TSF bits and the
    packet size adjust automatically.
    """
    body = payload.encode("ascii")
    if len(body) % 4:  # pad payload to a 32-bit word boundary with NULs
        body += b"\x00" * (4 - len(body) % 4)

    tsi = TSI_OTHER if include_timestamp else TSI_NONE
    tsf = TSF_REAL if include_timestamp else TSF_NONE

    header_words = 4  # header + stream id + 2 class-id words
    if include_timestamp:
        header_words += 3  # timestamp int (1) + timestamp frac (2)
    total_words = header_words + len(body) // 4

    header = (
        (PKT_TYPE_EXT_DATA_WITH_STREAM & 0xF) << 28
        | (1 << 27)                 # C: class id present
        | (0 << 26)                 # T: no trailer
        | (tsi & 0x3) << 24         # TSI [25:24]
        | (tsf & 0x3) << 22         # TSF [23:22]
        | (packet_count & 0xF) << 16
        | (total_words & 0xFFFF)
    )

    parts = [
        struct.pack(">I", header),
        struct.pack(">I", DISCOVERY_STREAM_ID),
        struct.pack(">I", FLEX_OUI & 0x00FFFFFF),  # class-id word 1: reserved(8)|OUI(24)
        struct.pack(">I", (DISCOVERY_INFO_CLASS << 16) | DISCOVERY_PACKET_CLASS),
    ]
    if include_timestamp:
        parts.append(struct.pack(">I", 0))  # integer timestamp (seconds)
        parts.append(struct.pack(">Q", 0))  # fractional timestamp (64-bit)
    parts.append(body)
    return b"".join(parts)

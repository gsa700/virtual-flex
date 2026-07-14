"""Minimal one-shot mDNS resolver — ``K4-SN<serial>.local`` -> IPv4, zero deps.

Sends a single A-record query to the mDNS multicast group with the
**unicast-response (QU) bit** set, so the responder answers straight back to our
ephemeral socket. That keeps us off the system resolver entirely: no ``SOA
local`` leak to unicast DNS (the v0.1.x bug), and no bind conflict with a running
avahi on :5353.

Used only to (re)learn the K4's IP when a cached address stops answering — never
on a per-connect basis.
"""
from __future__ import annotations

import asyncio
import logging
import socket
import struct

log = logging.getLogger("virtualflex.mdns")

_MDNS_ADDR = "224.0.0.251"
_MDNS_PORT = 5353
_TYPE_A = 1
_CLASS_IN = 1
_QU_BIT = 0x8000  # top bit of qclass: "unicast response requested"


def build_query(hostname: str, qid: int = 0) -> bytes:
    """Build an mDNS A-record query for `hostname`, unicast-response requested."""
    labels = hostname.rstrip(".").split(".")
    qname = b"".join(bytes([len(l)]) + l.encode("ascii") for l in labels) + b"\x00"
    header = struct.pack(">HHHHHH", qid, 0x0000, 1, 0, 0, 0)   # 1 question
    question = qname + struct.pack(">HH", _TYPE_A, _CLASS_IN | _QU_BIT)
    return header + question


def _skip_name(data: bytes, offset: int) -> int:
    """Return the offset just past the (possibly compressed) name at `offset`."""
    while offset < len(data):
        length = data[offset]
        if length == 0:
            return offset + 1
        if length & 0xC0 == 0xC0:       # compression pointer ends the name (2 bytes)
            return offset + 2
        offset += 1 + length
    return offset


def parse_response(data: bytes, hostname: str) -> str | None:
    """Return the first A-record IPv4 in an mDNS response, or None.

    We match on record TYPE=A rather than the (usually compressed) owner name:
    the query asked for a single host, so any A answer is the address we want.
    """
    if len(data) < 12:
        return None
    _qid, _flags, qd, an, _ns, _ar = struct.unpack(">HHHHHH", data[:12])
    offset = 12
    for _ in range(qd):                 # skip the echoed questions
        offset = _skip_name(data, offset) + 4      # + qtype + qclass
    for _ in range(an):                 # scan the answers
        offset = _skip_name(data, offset)
        if offset + 10 > len(data):
            return None
        rtype, _rclass, _ttl, rdlen = struct.unpack(">HHIH", data[offset:offset + 10])
        offset += 10
        if rtype == _TYPE_A and rdlen == 4 and offset + 4 <= len(data):
            return socket.inet_ntoa(data[offset:offset + 4])
        offset += rdlen
    return None


async def resolve(hostname: str, timeout: float = 2.0) -> str | None:
    """Resolve `hostname` (e.g. 'K4-SN01234.local') to an IPv4 via one-shot QU mDNS.

    Returns the address, or None if nothing answered within `timeout`. Never
    touches the system resolver, so it cannot leak to unicast DNS.
    """
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.setblocking(False)
    try:
        sock.bind(("", 0))              # ephemeral port; QU answers come back here
        await loop.sock_sendto(sock, build_query(hostname), (_MDNS_ADDR, _MDNS_PORT))
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            try:
                data = await asyncio.wait_for(loop.sock_recv(sock, 1500), remaining)
            except asyncio.TimeoutError:
                return None
            ip = parse_response(data, hostname)
            if ip:
                return ip
    finally:
        sock.close()

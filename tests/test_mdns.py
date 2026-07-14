import struct

from virtualflex import mdns


def test_build_query_sets_qu_bit_and_question():
    q = mdns.build_query("K4-SN01234.local", qid=0x1234)
    qid, _flags, qd, an, _ns, _ar = struct.unpack(">HHHHHH", q[:12])
    assert qid == 0x1234 and qd == 1 and an == 0
    assert b"\x0aK4-SN01234\x05local\x00" in q      # length-prefixed labels
    qtype, qclass = struct.unpack(">HH", q[-4:])
    assert qtype == 1                                # A record
    assert qclass & 0x8000                           # unicast-response (QU) bit
    assert qclass & 0x00FF == 1                      # IN class


def _response(ip: str) -> bytes:
    header = struct.pack(">HHHHHH", 0, 0x8400, 1, 1, 0, 0)   # 1 question + 1 answer
    qname = b"\x0aK4-SN01234\x05local\x00"
    question = qname + struct.pack(">HH", 1, 1)
    # answer name is a compression pointer (0xC00C) back to the question at offset 12
    rdata = bytes(int(o) for o in ip.split("."))
    answer = b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 120, 4) + rdata
    return header + question + answer


def test_parse_response_extracts_ip():
    assert mdns.parse_response(_response("192.0.2.105"), "K4-SN01234.local") == "192.0.2.105"


def test_parse_response_none_without_answer():
    header = struct.pack(">HHHHHH", 0, 0x8400, 0, 0, 0, 0)
    assert mdns.parse_response(header, "x.local") is None

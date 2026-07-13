"""Command dispatch tests using a fake stream writer."""
from virtualflex.config import Config
from virtualflex.protocol import ClientSession, parse_kv
from virtualflex.state import Radio


class FakeWriter:
    def __init__(self) -> None:
        self.data = b""
        self._closing = False

    def get_extra_info(self, _key):
        return ("127.0.0.1", 12345)

    def is_closing(self):
        return self._closing

    def write(self, b):
        self.data += b

    def close(self):
        self._closing = True

    async def drain(self):
        pass


def make_session():
    radio = Radio(Config.load(None))
    return ClientSession(radio, reader=None, writer=FakeWriter()), radio


def sent(session) -> str:
    return session.writer.data.decode()


def test_parse_kv():
    kv = parse_kv("create ip=192.168.0.14 port=9008 model=PowerGeniusXL".split())
    assert kv == {"ip": "192.168.0.14", "port": "9008", "model": "PowerGeniusXL"}


def test_amplifier_create_acks_with_handle():
    s, radio = make_session()
    s._dispatch("2", "amplifier create ip=192.168.0.14 port=9008 "
                     "model=PowerGeniusXL serial_num=2-50/18-0005 "
                     "ant=ANT1:PORTA,ANT2:PORTB")
    lines = sent(s).splitlines()
    assert lines[0].startswith("R2|0|0x")
    assert radio.amplifiers  # registered exactly one amplifier
    amp = next(iter(radio.amplifiers.values()))
    assert amp["model"] == "PowerGeniusXL"


def test_meter_create_returns_incrementing_ids():
    s, _ = make_session()
    s._dispatch("3", "meter create name=FWD type=AMP min=30.0 max=63.01 units=DBM")
    s._dispatch("4", "meter create name=RL type=AMP min=34.0 max=60.0 units=DB")
    lines = sent(s).splitlines()
    assert lines[0] == "R3|0|1"
    assert lines[1] == "R4|0|2"


def test_sub_slice_acks_then_dumps_status():
    s, _ = make_session()
    s._dispatch("5", "sub slice all")
    text = sent(s)
    assert "R5|0|" in text
    assert "slice 0" in text
    assert "RF_frequency=14.074000" in text
    assert "tx=1" in text


def test_ping_and_keepalive_ack():
    s, _ = make_session()
    s._dispatch("6", "keepalive enable")
    s._dispatch("7", "ping")
    lines = sent(s).splitlines()
    assert lines == ["R6|0|", "R7|0|"]
    assert s.keepalive is True


def test_unknown_command_is_acked_permissively():
    s, _ = make_session()
    s._dispatch("8", "wibble frobnicate")
    assert sent(s).splitlines() == ["R8|0|"]

"""Delta emission: runtime slice changes send terse lines (like a real Flex),
full dumps are reserved for subscribe time / structural changes. The Genius
boxes are embedded parsers — full ~1 KB dumps per dial click made the TGXL
display trail the K4 dial."""
from virtualflex.state import Radio


class StubClient:
    def __init__(self):
        self.lines = []
        self.handle = 0x40000000
        self.is_amplifier = False

    def subscribed(self, obj):
        return True

    def send_line(self, line):
        self.lines.append(line)

    def close(self):
        pass


def _radio_with_client():
    radio = Radio(config=object())      # config unused by the slice paths
    client = StubClient()
    radio.add_client(client)
    return radio, client


def test_freq_change_emits_short_deltas():
    radio, client = _radio_with_client()
    radio.update_slice(0, freq_hz=7074000)
    assert client.lines == [
        "S0|slice 0 RF_frequency=7.074000",
        "S0|transmit freq=7.074000",
    ]
    assert all(len(l) < 100 for l in client.lines)   # terse, not the 1 KB dump


def test_mode_change_rides_the_delta():
    radio, client = _radio_with_client()
    radio.update_slice(0, freq_hz=3925000, mode="LSB")
    assert client.lines == [
        "S0|slice 0 RF_frequency=3.925000 mode=LSB",
        "S0|transmit freq=3.925000 tx_slice_mode=LSB",
    ]


def test_structural_change_sends_full_status():
    radio, client = _radio_with_client()
    radio.update_slice(0, tx=False)                  # tx designation moved
    assert any("sample_rate=" in l for l in client.lines)   # full slice dump
    assert any("tx_antenna=" in l for l in client.lines)    # full transmit dump


def test_no_change_sends_nothing():
    radio, client = _radio_with_client()
    radio.update_slice(0, freq_hz=14074000, mode="USB")      # equals defaults
    assert client.lines == []

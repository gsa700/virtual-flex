"""Split-mode TX-frequency selection for the Hamlib source.

The amp/tuner/switch must follow the TRANSMIT frequency. In split that is VFO B
(get_split_freq), not the displayed VFO A — otherwise the stack switches bands
for the RX VFO and is wrong for the actual transmission.
"""
from virtualflex.rigsource.hamlib import HamlibSource

VFO_A = "14074000"   # displayed / RX VFO
VFO_B = "14200000"   # TX VFO in split


def test_simplex_uses_current_vfo():
    u = HamlibSource._tx_update(False, VFO_A, "", "USB")
    assert u == {"freq_hz": 14074000, "mode": "USB"}


def test_split_follows_tx_vfo_b():
    u = HamlibSource._tx_update(True, VFO_A, VFO_B, "USB")
    assert u["freq_hz"] == 14200000  # tracks the TX side, not VFO A


def test_split_falls_back_when_tx_freq_unavailable():
    # get_split_freq errored (RPRT) -> keep the current VFO rather than blank out.
    u = HamlibSource._tx_update(True, VFO_A, "RPRT -11", "USB")
    assert u["freq_hz"] == 14074000


def test_bad_mode_line_is_ignored():
    u = HamlibSource._tx_update(False, VFO_A, "", "RPRT -1")
    assert u == {"freq_hz": 14074000}

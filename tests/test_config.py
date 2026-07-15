"""Serial resolution — K4-hostname-derived FlexRadio serials."""
from virtualflex.config import Config, derive_flex_serial


def test_derive_from_k4_hostname():
    assert derive_flex_serial("FLEX-8600", "K4-SN01234.local") == "8600-0000-0000-1234"


def test_derive_case_insensitive_and_plain_host():
    assert derive_flex_serial("FLEX-8600", "k4-sn12345") == "8600-0000-0001-2345"


def test_derive_returns_none_for_ip():
    assert derive_flex_serial("FLEX-8600", "192.0.2.105") is None


def test_derive_model_without_digits_uses_zero_prefix():
    assert derive_flex_serial("FLEX", "K4-SN7") == "0000-0000-0000-0007"


def test_resolve_auto_uses_k4_hostname():
    cfg = Config(radio={"model": "FLEX-8600", "serial": "auto"}, network={},
                 k4={"hostname": "K4-SN01234.local"}, presence={})
    serial, note = cfg.resolve_serial()
    assert serial == "8600-0000-0000-1234"
    assert "auto-derived" in note


def test_resolve_explicit_serial_is_kept():
    cfg = Config(radio={"model": "FLEX-8600", "serial": "1900-0000-0000-0001"},
                 network={}, k4={}, presence={})
    assert cfg.resolve_serial() == ("1900-0000-0000-0001", "configured")


def test_resolve_auto_without_hostname_falls_back_to_placeholder():
    cfg = Config(radio={"model": "FLEX-8600", "serial": "auto"}, network={},
                 k4={"hostname": "192.0.2.105"}, presence={})
    serial, note = cfg.resolve_serial()
    assert serial == "0000-0000-0000-0000"
    assert "could not auto-derive" in note

import pathlib
import tempfile
import tomllib

from virtualflex.config import Config
from virtualflex.setup import (build_config, k4_serial_from_hostname,
                               load_existing, subnet_broadcast)


def test_subnet_broadcast_slash24():
    assert subnet_broadcast("192.0.2.14") == "10.0.1.255"
    assert subnet_broadcast("192.168.7.200") == "192.168.7.255"


def test_subnet_broadcast_fallback_on_garbage():
    assert subnet_broadcast("not-an-ip") == "255.255.255.255"


def test_build_config_is_valid_toml_with_choices():
    cfg = build_config(k4_ip="192.0.2.105", k4_hostname="K4-SN01234.local",
                       serial="8600-0000-0000-1234", callsign="AB0R",
                       nickname="VirtualFlex", broadcast="10.0.1.255")
    data = tomllib.loads(cfg)                      # must parse
    assert data["k4"]["ip"] == "192.0.2.105"
    assert data["radio"]["serial"] == "8600-0000-0000-1234"
    assert data["network"]["broadcast_address"] == "10.0.1.255"


def test_k4_serial_from_hostname():
    assert k4_serial_from_hostname("K4-SN01234.local") == "01234"
    assert k4_serial_from_hostname("k4-sn01234.LOCAL") == "01234"   # any case
    assert k4_serial_from_hostname("someother.local") == ""
    assert k4_serial_from_hostname("") == ""


def test_load_existing_roundtrips_a_generated_config():
    # Re-running setup pre-fills from the previous run's file.
    cfg = build_config(k4_ip="192.0.2.105", k4_hostname="K4-SN01234.local",
                       serial="8600-0000-0000-1234", callsign="AB0R",
                       nickname="VirtualFlex", broadcast="10.0.1.255",
                       discovery_targets=["192.0.2.100", "192.0.2.101"])
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp) / "config.toml"
        p.write_text(cfg)
        existing = load_existing(p)
    assert existing["radio"]["callsign"] == "AB0R"
    assert existing["network"]["discovery_targets"] == ["192.0.2.100", "192.0.2.101"]
    assert k4_serial_from_hostname(existing["k4"]["hostname"]) == "01234"


def test_load_existing_tolerates_missing_or_bad_file():
    assert load_existing(pathlib.Path("/nonexistent/config.toml")) == {}
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp) / "config.toml"
        p.write_text("not [valid toml ===")
        assert load_existing(p) == {}               # fresh-install behavior


def test_build_config_merges_with_defaults():
    cfg = build_config(k4_ip="192.0.2.105", k4_hostname="K4-SN01234.local",
                       serial="8600-0000-0000-1234", callsign="AB0R",
                       nickname="VirtualFlex", broadcast="10.0.1.255")
    # written to disk + loaded, the omitted keys fall back to defaults
    import tempfile, os
    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
        fh.write(cfg)
        p = fh.name
    try:
        c = Config.load(p)
        assert c.k4["cat_port"] == 9200            # default filled in
        assert c.presence["absent_after"] == 5.0   # default filled in
        assert c.radio["serial"] == "8600-0000-0000-1234"  # our choice preserved
    finally:
        os.unlink(p)

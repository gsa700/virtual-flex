import tomllib

from virtualflex.config import Config
from virtualflex.setup import build_config, subnet_broadcast


def test_subnet_broadcast_slash24():
    assert subnet_broadcast("10.0.1.14") == "10.0.1.255"
    assert subnet_broadcast("192.168.7.200") == "192.168.7.255"


def test_subnet_broadcast_fallback_on_garbage():
    assert subnet_broadcast("not-an-ip") == "255.255.255.255"


def test_build_config_is_valid_toml_with_choices():
    cfg = build_config(k4_ip="10.0.1.105", k4_hostname="K4-SN00895.local",
                       serial="8600-0000-0000-0895", callsign="AB0R",
                       nickname="VirtualFlex", broadcast="10.0.1.255")
    data = tomllib.loads(cfg)                      # must parse
    assert data["k4"]["ip"] == "10.0.1.105"
    assert data["radio"]["serial"] == "8600-0000-0000-0895"
    assert data["network"]["broadcast_address"] == "10.0.1.255"


def test_build_config_merges_with_defaults():
    cfg = build_config(k4_ip="10.0.1.105", k4_hostname="K4-SN00895.local",
                       serial="8600-0000-0000-0895", callsign="AB0R",
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
        assert c.radio["serial"] == "8600-0000-0000-0895"  # our choice preserved
    finally:
        os.unlink(p)

import asyncio
import pathlib
import tempfile
import tomllib

from virtualflex.config import Config
from virtualflex.setup import (build_config, k4_serial_from_hostname,
                               load_existing, normalize_k4_serial,
                               scan_for_genius, scan_for_k4s, subnet_broadcast)


def test_subnet_broadcast_slash24():
    assert subnet_broadcast("192.0.2.14") == "192.0.2.255"
    assert subnet_broadcast("192.168.7.200") == "192.168.7.255"


def test_subnet_broadcast_fallback_on_garbage():
    assert subnet_broadcast("not-an-ip") == "255.255.255.255"


def test_build_config_is_valid_toml_with_choices():
    cfg = build_config(k4_ip="192.0.2.105", k4_hostname="K4-SN01234.local",
                       serial="8600-0000-0000-1234", callsign="AB0R",
                       nickname="VirtualFlex", broadcast="192.0.2.255")
    data = tomllib.loads(cfg)                      # must parse
    assert data["k4"]["ip"] == "192.0.2.105"
    assert data["radio"]["serial"] == "8600-0000-0000-1234"
    assert data["network"]["broadcast_address"] == "192.0.2.255"


def test_k4_serial_from_hostname():
    assert k4_serial_from_hostname("K4-SN01234.local") == "01234"
    assert k4_serial_from_hostname("k4-sn01234.LOCAL") == "01234"   # any case
    assert k4_serial_from_hostname("someother.local") == ""
    assert k4_serial_from_hostname("") == ""


def test_load_existing_roundtrips_a_generated_config():
    # Re-running setup pre-fills from the previous run's file.
    cfg = build_config(k4_ip="192.0.2.105", k4_hostname="K4-SN01234.local",
                       serial="8600-0000-0000-1234", callsign="AB0R",
                       nickname="VirtualFlex", broadcast="192.0.2.255",
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


def test_normalize_k4_serial_zero_pads():
    # The K4 hostname pads to 5 digits: typing '1234' must find K4-SN01234.
    assert normalize_k4_serial("1234") == "01234"
    assert normalize_k4_serial("01234") == "01234"
    assert normalize_k4_serial(" 42 ") == "00042"
    assert normalize_k4_serial("123456") == "123456"   # >=5 digits untouched
    assert normalize_k4_serial("ABC12") == "ABC12"     # non-digits untouched
    assert normalize_k4_serial("") == ""


def test_scan_finds_a_k4_and_reads_its_serial():
    async def scenario():
        async def cat(reader, writer):
            data = await reader.read(16)
            if b"SN;" in data:
                writer.write(b"SN1234;")               # radio replies unpadded
                await writer.drain()
            writer.close()

        srv = await asyncio.start_server(cat, "127.0.0.1", 0)
        port = srv.sockets[0].getsockname()[1]
        found = await scan_for_k4s("127.0.0.1", port=port, hosts=["127.0.0.1"])
        srv.close()
        assert found == [("127.0.0.1", "01234")]      # serial zero-padded

    asyncio.run(scenario())


def test_scan_skips_dead_hosts_keeps_silent_listeners():
    async def scenario():
        async def mute(reader, writer):
            await reader.read(16)                     # accepts, never answers
            writer.close()

        srv = await asyncio.start_server(mute, "127.0.0.1", 0)
        port = srv.sockets[0].getsockname()[1]
        # 127.0.0.2 refuses (nothing listening) -> excluded entirely
        found = await scan_for_k4s("127.0.0.1", port=port,
                                   hosts=["127.0.0.1", "127.0.0.2"],
                                   connect_timeout=0.3)
        srv.close()
        assert found == [("127.0.0.1", "")]           # listener w/o serial kept

    asyncio.run(scenario())


def test_scan_finds_genius_boxes_by_port():
    async def scenario():
        async def accept(reader, writer):
            writer.close()

        pg = await asyncio.start_server(accept, "127.0.0.1", 0)
        tg = await asyncio.start_server(accept, "127.0.0.1", 0)
        pg_port = pg.sockets[0].getsockname()[1]
        tg_port = tg.sockets[0].getsockname()[1]
        found = await scan_for_genius(
            "127.0.0.1", hosts=["127.0.0.1"],
            ports={pg_port: "Power Genius XL", tg_port: "Tuner Genius XL"})
        pg.close()
        tg.close()
        assert ("127.0.0.1", "Power Genius XL") in found
        assert ("127.0.0.1", "Tuner Genius XL") in found

    asyncio.run(scenario())


def test_scan_for_genius_empty_when_nothing_listens():
    async def scenario():
        found = await scan_for_genius("127.0.0.1", hosts=["127.0.0.2"],
                                      ports={9008: "Power Genius XL"},
                                      connect_timeout=0.3)
        assert found == []

    asyncio.run(scenario())


def test_build_config_merges_with_defaults():
    cfg = build_config(k4_ip="192.0.2.105", k4_hostname="K4-SN01234.local",
                       serial="8600-0000-0000-1234", callsign="AB0R",
                       nickname="VirtualFlex", broadcast="192.0.2.255")
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

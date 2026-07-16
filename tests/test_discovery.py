"""Discovery target selection: broadcast by default, unicast-only when
discovery_targets is set (augmented with currently-connected client IPs)."""
from virtualflex.config import Config
from virtualflex.discovery import DiscoveryBroadcaster
from virtualflex.state import Radio


class StubClient:
    def __init__(self, ip):
        self.peer = (ip, 55555)
        self.handle = 0x40000000
        self.is_amplifier = False

    def subscribed(self, obj):
        return False

    def send_line(self, line):
        pass

    def close(self):
        pass


def _radio(**network_overrides):
    cfg = Config.load(None)
    cfg.network.update(network_overrides)
    return Radio(cfg)


def test_default_is_broadcast():
    radio = _radio(broadcast_address="192.0.2.255")
    d = DiscoveryBroadcaster(radio)
    assert d.targets() == ["192.0.2.255"]


def test_unicast_targets_replace_broadcast():
    radio = _radio(broadcast_address="192.0.2.255",
                   discovery_targets=["192.0.2.100", "192.0.2.101"])
    d = DiscoveryBroadcaster(radio)
    assert d.targets() == ["192.0.2.100", "192.0.2.101"]
    assert "192.0.2.255" not in d.targets()          # nothing broadcast


def test_unicast_includes_connected_clients():
    radio = _radio(discovery_targets=["192.0.2.100"])
    radio.add_client(StubClient("192.0.2.102"))      # box connected but not listed
    d = DiscoveryBroadcaster(radio)
    assert d.targets() == ["192.0.2.100", "192.0.2.102"]


def test_blank_entries_ignored():
    radio = _radio(discovery_targets=["", "  ", "192.0.2.100"])
    d = DiscoveryBroadcaster(radio)
    assert d.unicast_targets == ["192.0.2.100"]

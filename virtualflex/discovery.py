"""UDP discovery broadcaster.

Emits a FlexRadio VITA-49 discovery packet at a fixed cadence so the PGXL (and
SmartSDR, useful for testing) sees the virtual radio and can match its serial.
"""
from __future__ import annotations

import asyncio
import logging
import socket

from .state import Radio
from .vita49 import build_discovery_packet

log = logging.getLogger("virtualflex.discovery")


class DiscoveryBroadcaster:
    def __init__(self, radio: Radio) -> None:
        self.radio = radio
        net = radio.config.network
        self.broadcast_addr = net["broadcast_address"]
        self.port = int(net["discovery_port"])
        self.interval = float(net["discovery_interval"])

    def _payload(self) -> str:
        r = self.radio.config.radio
        ip = self.radio.config.advertise_ip()
        port = self.radio.config.network["command_port"]
        # Spaces in name/nickname are encoded as underscores on the wire.
        name = str(r["name"]).replace(" ", "_")
        nickname = str(r["nickname"]).replace(" ", "_")
        fields = [
            f"model={r['model']}",
            f"serial={r['serial']}",
            f"version={r['version']}",
            f"name={name}",
            f"nickname={nickname}",
            f"callsign={r['callsign']}",
            f"ip={ip}",
            f"port={port}",
            "status=Available",
            "discovery_protocol_version=3.0.0.2",  # confirm exact value from an 8600 capture
        ]
        return " ".join(fields)

    async def run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(False)
        loop = asyncio.get_running_loop()
        count = 0
        log.info("broadcasting discovery to %s:%d every %.1fs (serial=%s)",
                 self.broadcast_addr, self.port, self.interval,
                 self.radio.config.radio["serial"])
        try:
            while True:
                pkt = build_discovery_packet(self._payload(), packet_count=count)
                try:
                    await loop.sock_sendto(sock, pkt, (self.broadcast_addr, self.port))
                except OSError as exc:
                    log.warning("discovery send failed: %s", exc)
                count = (count + 1) & 0xF
                await asyncio.sleep(self.interval)
        finally:
            sock.close()

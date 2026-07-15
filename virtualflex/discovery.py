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
        # Field set modeled on a live FLEX-8600M capture (fw 4.2.20, 31 fields).
        # GUI clients (Maestro / SmartSDR) parse far more of this card than the
        # Genius boxes do — missing keys can wedge a Maestro's boot-time radio
        # scan ("please wait..."), so emit the full complement.
        fields = [
            "discovery_protocol_version=3.1.0.4",
            f"model={r['model']}",
            f"serial={r['serial']}",
            f"version={r['version']}",
            f"name={name}",
            f"nickname={nickname}",
            f"callsign={r['callsign']}",
            f"ip={ip}",
            f"port={port}",
            "status=Available",
            "inuse_ip=",
            "inuse_host=",
            "max_licensed_version=v3",
            "radio_license_id=00-1C-2D-00-08-95",
            "fpc_mac=00:1c:2d:00:08:95",
            "wan_connected=0",
            "licensed_clients=2",
            "available_clients=2",
            "max_panadapters=4",
            "available_panadapters=4",
            "max_slices=4",
            "available_slices=4",
            "gui_client_ips=",
            "gui_client_hosts=",
            "gui_client_programs=",
            "gui_client_stations=",
            "gui_client_handles=",
            "min_software_version=3.8.0.0",
            "external_port_link=1",
            "license_is_unknown=0",
            "is_system_model=0",
            "turf_region=USA",
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

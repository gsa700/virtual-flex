"""Configuration loading (TOML) with defaults. Stdlib ``tomllib`` only."""
from __future__ import annotations

import socket
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULTS: dict = {
    "radio": {
        "model": "FLEX-8600",
        "serial": "1234-5678-9012-3456",
        "version": "3.6.19.35",
        "name": "VirtualFlex",
        "nickname": "VirtualFlex",
        "callsign": "AB0R",
    },
    "network": {
        "command_port": 4992,
        "discovery_port": 4992,
        "broadcast_address": "255.255.255.255",
        "discovery_interval": 1.0,
        "advertise_ip": "",
    },
    "rig": {
        "source": "sim",
        "sim": {"frequency": 14074000, "mode": "USB", "sweep_hz_per_sec": 0},
        "hamlib": {"host": "127.0.0.1", "port": 4532, "poll_interval": 0.1},
    },
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class Config:
    radio: dict = field(default_factory=dict)
    network: dict = field(default_factory=dict)
    rig: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path | None) -> "Config":
        data = dict(_DEFAULTS)
        if path:
            with open(path, "rb") as fh:
                data = _deep_merge(data, tomllib.load(fh))
        return cls(radio=data["radio"], network=data["network"], rig=data["rig"])

    def advertise_ip(self) -> str:
        configured = self.network.get("advertise_ip") or ""
        return configured if configured else detect_local_ip()


def detect_local_ip() -> str:
    """Best-effort local IPv4. Opens a UDP socket toward a public address (no
    packets are actually sent) and reads back the chosen source address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()

"""Configuration loading (TOML) with defaults. Stdlib ``tomllib`` only."""
from __future__ import annotations

import copy
import re
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
    "ptt": {
        "source": "none",  # "none" = interlock stays RECEIVE; "k4cat" = detect K4 TX over CAT
        "k4cat": {"host": "127.0.0.1", "port": 9200, "poll_interval": 0.01},
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
    ptt: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path | None) -> "Config":
        data = copy.deepcopy(_DEFAULTS)
        if path:
            with open(path, "rb") as fh:
                data = _deep_merge(data, tomllib.load(fh))
        return cls(radio=data["radio"], network=data["network"],
                   rig=data["rig"], ptt=data["ptt"])

    def advertise_ip(self) -> str:
        configured = self.network.get("advertise_ip") or ""
        return configured if configured else detect_local_ip()

    def resolve_serial(self) -> tuple[str, str]:
        """Resolve the advertised serial, returning ``(serial, note)``.

        If ``radio.serial`` is blank or ``"auto"``, derive it from the K4's
        hostname in ``[ptt.k4cat].host`` (e.g. ``K4-SN00895`` -> the K4 serial).
        Otherwise the configured value is used verbatim. On failure to derive we
        fall back to the built-in placeholder so the app still starts.
        """
        configured = str(self.radio.get("serial", "")).strip()
        if configured and configured.lower() != "auto":
            return configured, "configured"

        host = ""
        if str(self.ptt.get("source", "none")).lower() == "k4cat":
            host = str(self.ptt.get("k4cat", {}).get("host", ""))
        derived = derive_flex_serial(str(self.radio.get("model", "")), host)
        if derived:
            return derived, f"auto-derived from K4 hostname '{host}'"

        placeholder = _DEFAULTS["radio"]["serial"]
        return placeholder, (
            "could not auto-derive a serial (no K4-SN<n> hostname on "
            f"ptt.k4cat.host='{host}', source={self.ptt.get('source')}) - "
            "using placeholder; set radio.serial explicitly")


def derive_flex_serial(model: str, host: str) -> str | None:
    """Build a FlexRadio-style ``NNNN-NNNN-NNNN-NNNN`` serial from a K4 hostname.

    Elecraft K4s answer mDNS as ``K4-SN<digits>`` (e.g. ``K4-SN00895.local``).
    We take those digits as the low bits and prefix the emulated model number,
    e.g. model ``FLEX-8600`` + ``K4-SN00895`` -> ``8600-0000-0000-0895``. The
    model prefix can't collide with a real 8600 serial (those start with a year
    like ``1926``), and the tail is recognizably the operator's K4.

    Returns ``None`` if no ``SN<digits>`` is present (e.g. host is a raw IP).
    """
    m = re.search(r"SN(\d+)", host or "", re.IGNORECASE)
    if not m:
        return None
    prefix = ("".join(ch for ch in (model or "") if ch.isdigit()) or "0000")[:4].rjust(4, "0")
    tail = m.group(1)[-12:].rjust(12, "0")
    return f"{prefix}-{tail[0:4]}-{tail[4:8]}-{tail[8:12]}"


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

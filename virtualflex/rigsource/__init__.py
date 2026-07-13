"""Rig data sources: where the virtual radio's frequency/mode/TX comes from."""
from __future__ import annotations

from ..state import Radio
from .base import RigSource
from .hamlib import HamlibSource
from .sim import SimSource


def build_source(radio: Radio) -> RigSource:
    rig = radio.config.rig
    kind = str(rig.get("source", "sim")).lower()
    if kind == "sim":
        cfg = rig.get("sim", {})
        return SimSource(
            radio,
            frequency=int(cfg.get("frequency", 14074000)),
            mode=str(cfg.get("mode", "USB")),
            sweep_hz_per_sec=float(cfg.get("sweep_hz_per_sec", 0)),
        )
    if kind == "hamlib":
        cfg = rig.get("hamlib", {})
        return HamlibSource(
            radio,
            host=str(cfg.get("host", "127.0.0.1")),
            port=int(cfg.get("port", 4532)),
            poll_interval=float(cfg.get("poll_interval", 0.1)),
        )
    raise ValueError(f"unknown rig source: {kind!r}")


__all__ = ["RigSource", "SimSource", "HamlibSource", "build_source"]

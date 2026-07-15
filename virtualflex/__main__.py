"""Entry point: ``python -m virtualflex --config config.toml``.

Wires the native K4 CAT client to the presence supervisor: while the K4 is
reachable we advertise and serve the Genius stack; when it goes away we tear the
whole thing down so the stack reverts to its no-transceiver antenna.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from . import __version__, mdns
from .config import Config
from .discovery import DiscoveryBroadcaster
from .k4 import K4Client
from .server import CommandServer
from .state import Radio
from .supervisor import Supervisor

log = logging.getLogger("virtualflex")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="virtual-flex", description=__doc__)
    p.add_argument("-c", "--config", help="path to config.toml")
    p.add_argument("--host", default="0.0.0.0", help="bind address for the command server")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    p.add_argument("-V", "--version", action="version",
                   version=f"virtual-flex {__version__}")
    return p.parse_args(argv)


async def _initial_ip(cfg: Config) -> str:
    """The K4's address to start from: the cached IP, or a one-shot mDNS lookup
    of the hostname if no IP is configured yet."""
    ip = str(cfg.k4.get("ip", "")).strip()
    host = str(cfg.k4.get("hostname", "")).strip()
    if not ip and host:
        ip = await mdns.resolve(host) or ""
        if ip:
            log.info("resolved %s -> %s via mDNS", host, ip)
    return ip


async def run(cfg: Config, bind_host: str) -> None:
    radio = Radio(cfg)
    server = CommandServer(radio)
    discovery = DiscoveryBroadcaster(radio)
    command_port = int(cfg.network["command_port"])
    discovery_task: asyncio.Task | None = None

    async def go_online() -> None:
        nonlocal discovery_task
        await server.start(bind_host, command_port)
        discovery_task = asyncio.create_task(discovery.run())

    async def go_offline() -> None:
        nonlocal discovery_task
        if discovery_task is not None:
            discovery_task.cancel()
            try:
                await discovery_task
            except asyncio.CancelledError:
                pass
            discovery_task = None
        await server.stop()

    ip = await _initial_ip(cfg)
    if not ip:
        log.error("no K4 address: set [k4].ip or a resolvable [k4].hostname")
        return

    k4 = K4Client(
        ip=ip, port=int(cfg.k4["cat_port"]),
        hostname=str(cfg.k4.get("hostname", "")) or None,
        ptt_interval=float(cfg.k4["ptt_interval"]),
        freq_interval=float(cfg.k4["freq_interval"]),
        stale_after=float(cfg.k4["stale_after"]),
        on_tx=lambda freq, mode: radio.update_slice(0, freq_hz=freq, mode=mode),
        on_ptt=radio.set_transmit,
    )
    supervisor = Supervisor(
        is_present=k4.is_present, go_online=go_online, go_offline=go_offline,
        present_after=float(cfg.presence["present_after"]),
        absent_after=float(cfg.presence["absent_after"]),
        poll_interval=float(cfg.presence["poll_interval"]),
    )

    log.info("virtual-flex %s up - model=%s serial=%s advertising ip=%s; K4 at %s:%d",
             __version__, cfg.radio["model"], cfg.radio["serial"],
             cfg.advertise_ip(), ip, int(cfg.k4["cat_port"]))
    try:
        await asyncio.gather(k4.run(), supervisor.run())
    finally:
        await go_offline()   # on shutdown, let the stack fall back to its no-transceiver antenna


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "setup":
        from . import setup
        raise SystemExit(setup.run(argv[1:]))
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("asyncio").setLevel(logging.WARNING)  # keep our DEBUG readable
    cfg = Config.load(args.config)
    serial, note = cfg.resolve_serial()
    cfg.radio["serial"] = serial
    (log.warning if note.startswith("could not") else log.info)(
        "radio serial=%s (%s)", serial, note)
    try:
        asyncio.run(run(cfg, args.host))
    except KeyboardInterrupt:
        log.info("shutting down")


if __name__ == "__main__":
    main()

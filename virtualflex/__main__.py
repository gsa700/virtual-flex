"""Entry point: ``python -m virtualflex --config config.toml``."""
from __future__ import annotations

import argparse
import asyncio
import logging

from . import __version__
from .config import Config
from .discovery import DiscoveryBroadcaster
from .ptt import K4PttMonitor
from .rigsource import build_source
from .server import CommandServer
from .state import Radio

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


async def run(cfg: Config, host: str) -> None:
    radio = Radio(cfg)
    server = CommandServer(radio)
    await server.start(host, int(cfg.network["command_port"]))
    discovery = DiscoveryBroadcaster(radio)
    source = build_source(radio)

    tasks = [server.serve(), discovery.run(), source.run()]
    if str(cfg.ptt.get("source", "none")).lower() == "k4cat":
        k = cfg.ptt.get("k4cat", {})
        monitor = K4PttMonitor(radio, host=str(k.get("host", "127.0.0.1")),
                               port=int(k.get("port", 9200)),
                               poll_interval=float(k.get("poll_interval", 0.01)))
        tasks.append(monitor.run())
        log.info("K4 CAT PTT detection enabled (%s:%s)", k.get("host"), k.get("port"))

    log.info("virtual-flex %s up - model=%s serial=%s advertising ip=%s",
             __version__, cfg.radio["model"], cfg.radio["serial"], cfg.advertise_ip())
    await asyncio.gather(*tasks)


def main(argv: list[str] | None = None) -> None:
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

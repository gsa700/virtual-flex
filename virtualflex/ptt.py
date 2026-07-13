"""Low-latency transmit detection over the Elecraft K4's network CAT port.

Keeps a dedicated connection to the K4 and fast-polls ``TQX;`` (transmit query,
holdoff excluded) so a key-down is seen within a few ms — ideally inside the
K4's 25 ms "Key Out to RF Out" window — and relayed to the 4O3A stack as
interlock TRANSMITTING before RF appears. Runs independently of the (slower)
frequency/mode poll so keying latency isn't tied to it.

This path is K4-specific by design; other radios can fall back to hamlib PTT.
On any link loss it fails safe to RECEIVE.
"""
from __future__ import annotations

import asyncio
import logging
import re

from .state import Radio

log = logging.getLogger("virtualflex.ptt")

# The K4 answers both TQ; and TQX; with "TQn;" (n = 1 when logically in TX).
_TQ = re.compile(r"TQ([01])")


class K4PttMonitor:
    def __init__(self, radio: Radio, *, host: str, port: int,
                 poll_interval: float) -> None:
        self.radio = radio
        self.host = host
        self.port = port
        self.poll_interval = poll_interval

    async def run(self) -> None:
        while True:
            try:
                await self._loop()
            except (ConnectionError, OSError, asyncio.IncompleteReadError) as exc:
                log.warning("K4 CAT PTT link lost (%s); failing safe to RX, retry 2s", exc)
                self.radio.set_transmit(False)
                await asyncio.sleep(2)

    async def _loop(self) -> None:
        reader, writer = await asyncio.open_connection(self.host, self.port)
        log.info("K4 PTT monitor connected to %s:%d (TQX every %.0f ms)",
                 self.host, self.port, self.poll_interval * 1000)
        buf = ""
        try:
            while True:
                writer.write(b"TQX;")
                await writer.drain()
                try:
                    data = await asyncio.wait_for(reader.read(256), timeout=1.0)
                except asyncio.TimeoutError:
                    data = b""
                if not data:
                    if reader.at_eof():
                        raise ConnectionError("K4 closed the CAT connection")
                else:
                    buf += data.decode("ascii", "replace")
                    while ";" in buf:
                        stmt, _, buf = buf.partition(";")
                        m = _TQ.match(stmt.strip())
                        if m:
                            self.radio.set_transmit(m.group(1) == "1")
                await asyncio.sleep(self.poll_interval)
        finally:
            writer.close()

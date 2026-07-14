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
    _MIN_BACKOFF = 2.0    # prompt reconnect after a live link drops
    _MAX_BACKOFF = 60.0   # ceiling while the radio stays unreachable

    def __init__(self, radio: Radio, *, host: str, port: int,
                 poll_interval: float) -> None:
        self.radio = radio
        self.host = host
        self.port = port
        self.poll_interval = poll_interval
        self._link_up = False  # True once a connection is established this round

    @classmethod
    def _next_backoff(cls, delay: float) -> float:
        """Exponential backoff, capped at _MAX_BACKOFF.

        Matters when the K4 is off: each reconnect re-resolves the ``.local``
        hostname, and a failed mDNS lookup leaks SOA queries to unicast DNS. A
        fixed 2 s retry turns a powered-off radio into a steady DNS flood
        (~22k queries/day was observed hitting Pi-hole); backing off to one
        attempt per 60 s cuts that to a trickle. Reset to _MIN_BACKOFF on a
        successful connect so a brief drop still reconnects fast.
        """
        return min(delay * 2, cls._MAX_BACKOFF)

    async def run(self) -> None:
        backoff = self._MIN_BACKOFF
        while True:
            self._link_up = False
            try:
                await self._loop()
            except (ConnectionError, OSError, asyncio.IncompleteReadError) as exc:
                self.radio.set_transmit(False)  # fail safe to RX
                if self._link_up:
                    # A working link dropped (radio went away mid-session):
                    # reconnect promptly and reset the backoff.
                    log.warning("K4 CAT PTT link lost (%s); RX-safe, reconnecting", exc)
                    backoff = self._MIN_BACKOFF
                    await asyncio.sleep(backoff)
                else:
                    # Never connected this round (radio off / unreachable): back
                    # off so we don't flood DNS re-resolving the .local name.
                    log.warning("K4 CAT PTT unreachable (%s); RX-safe, retry in %.0fs", exc, backoff)
                    await asyncio.sleep(backoff)
                    backoff = self._next_backoff(backoff)

    async def _loop(self) -> None:
        reader, writer = await asyncio.open_connection(self.host, self.port)
        self._link_up = True
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

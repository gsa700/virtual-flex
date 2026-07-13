"""Hamlib (rigctld) rig source — Phase 3.

Polls a running ``rigctld`` for frequency, mode and PTT and feeds them into the
shared radio state. Start rigctld against the K4 over its network CAT port::

    rigctld -m <K4_model> -r <k4_ip>:9200 -t 4532

NOTE: written from the rigctld protocol spec; validate against a live K4 before
relying on it. Reconnects automatically if rigctld goes away.
"""
from __future__ import annotations

import asyncio
import logging

from ..state import Radio
from .base import RigSource

log = logging.getLogger("virtualflex.rig.hamlib")


class HamlibSource(RigSource):
    def __init__(self, radio: Radio, *, host: str, port: int,
                 poll_interval: float) -> None:
        super().__init__(radio)
        self.host = host
        self.port = port
        self.poll_interval = poll_interval

    async def run(self) -> None:
        while True:
            try:
                await self._poll_loop()
            except (ConnectionError, OSError, asyncio.IncompleteReadError) as exc:
                log.warning("rigctld connection lost (%s); retrying in 2s", exc)
                await asyncio.sleep(2)

    async def _poll_loop(self) -> None:
        reader, writer = await asyncio.open_connection(self.host, self.port)
        log.info("connected to rigctld at %s:%d", self.host, self.port)
        try:
            while True:
                # Frequency + mode are what the amp follows. `slice.tx=1` is a
                # static "this is the transmit slice" designation, not PTT state —
                # keying stays on the hardware PTT line — so we don't touch it here.
                # (Split-across-bands, where the TX VFO differs, is a later refinement.)
                freq = await self._query1(reader, writer, "f")
                mode_lines = await self._query(reader, writer, "m", 2)

                update: dict = {}
                if freq and freq.lstrip("-").isdigit():
                    update["freq_hz"] = int(freq)
                if mode_lines and not mode_lines[0].startswith("RPRT"):
                    update["mode"] = mode_lines[0]
                if update:
                    self.radio.update_slice(0, **update)

                await asyncio.sleep(self.poll_interval)
        finally:
            writer.close()

    async def _query(self, reader: asyncio.StreamReader,
                     writer: asyncio.StreamWriter, cmd: str, nlines: int) -> list[str]:
        writer.write((cmd + "\n").encode())
        await writer.drain()
        out = []
        for _ in range(nlines):
            line = await reader.readline()
            if not line:
                raise ConnectionError("rigctld closed the connection")
            out.append(line.decode("ascii", "replace").strip())
        return out

    async def _query1(self, reader: asyncio.StreamReader,
                      writer: asyncio.StreamWriter, cmd: str) -> str:
        return (await self._query(reader, writer, cmd, 1))[0]

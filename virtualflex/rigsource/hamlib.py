"""Hamlib (rigctld) rig source — Phase 3.

Polls a running ``rigctld`` for frequency, mode and PTT and feeds them into the
shared radio state. Start rigctld against the K4 over its network CAT port::

    rigctld -m <K4_model> -r <k4_host>:9200 -t 4532   # k4_host: IP or K4-SN<serial>.local

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
                # The stack follows the TRANSMIT frequency. In split that's VFO B,
                # not the displayed VFO A — so when split is on we feed slice 0 the
                # split TX freq (get_split_freq) instead of get_freq. `slice.tx=1`
                # is a static "this is the transmit slice" designation, not PTT.
                split_on = await self._get_split(reader, writer)
                cur_freq = await self._query1(reader, writer, "f")
                mode_lines = await self._query(reader, writer, "m", 2)
                tx_freq = ""
                if split_on:
                    tx_freq = await self._query1(reader, writer, "i")  # get_split_freq

                mode0 = mode_lines[0] if mode_lines else ""
                update = self._tx_update(split_on, cur_freq, tx_freq, mode0)
                if update:
                    self.radio.update_slice(0, **update)

                await asyncio.sleep(self.poll_interval)
        finally:
            writer.close()

    @staticmethod
    def _tx_update(split_on: bool, cur_freq: str, tx_freq: str, mode0: str) -> dict:
        """Pick the freq/mode the stack should track. In split the amp must follow
        the TX VFO (VFO B) via get_split_freq; otherwise the current VFO. Falls back
        to the current VFO if the split freq is missing/errored so we never blank."""
        use_tx = split_on and tx_freq.lstrip("-").isdigit()
        freq = tx_freq if use_tx else cur_freq
        update: dict = {}
        if freq and freq.lstrip("-").isdigit():
            update["freq_hz"] = int(freq)
        if mode0 and not mode0.startswith("RPRT"):
            update["mode"] = mode0
        return update

    async def _get_split(self, reader: asyncio.StreamReader,
                         writer: asyncio.StreamWriter) -> bool:
        """get_split_vfo (`s`) -> True if split is on. Tolerant of backends that
        answer with a single RPRT error line (won't block waiting for a VFO line)."""
        writer.write(b"s\n")
        await writer.drain()
        line = await reader.readline()
        if not line:
            raise ConnectionError("rigctld closed the connection")
        first = line.decode("ascii", "replace").strip()
        if first.startswith("RPRT"):
            return False  # split not reported by this backend
        await reader.readline()  # consume the TX-VFO line (2nd line of the reply)
        return first == "1"

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

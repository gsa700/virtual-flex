"""Simulated rig source for Phase-1 bring-up (no real radio needed).

Reports a static frequency, or slowly sweeps a ~350 kHz span so you can watch
the PGXL/TGXL/AGXL follow band changes on the bench.
"""
from __future__ import annotations

import asyncio
import logging

from ..state import Radio
from .base import RigSource

log = logging.getLogger("virtualflex.rig.sim")

_TICK = 0.5  # seconds between sweep steps


class SimSource(RigSource):
    def __init__(self, radio: Radio, *, frequency: int, mode: str,
                 sweep_hz_per_sec: float) -> None:
        super().__init__(radio)
        self.frequency = frequency
        self.mode = mode
        self.sweep = sweep_hz_per_sec

    async def run(self) -> None:
        self.radio.update_slice(0, freq_hz=self.frequency, mode=self.mode, tx=True)
        log.info("sim source: %.6f MHz %s (sweep %s Hz/s)",
                 self.frequency / 1e6, self.mode, self.sweep or "off")
        if self.sweep <= 0:
            while True:  # static: nothing to do but stay alive
                await asyncio.sleep(3600)

        low, span = self.frequency, 350_000
        freq = low
        while True:
            await asyncio.sleep(_TICK)
            freq += int(self.sweep * _TICK)
            if freq > low + span:
                freq = low
            self.radio.update_slice(0, freq_hz=freq)

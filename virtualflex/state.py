"""Shared radio state: slices, registered objects, and connected clients.

The ``Radio`` is the single source of truth. A rig source (sim or hamlib) calls
:meth:`Radio.update_slice`; that pushes ``S|slice ...`` status to every client
subscribed to the slice subsystem — which is how the PGXL learns the band.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config
    from .protocol import ClientSession

log = logging.getLogger("virtualflex.state")

# hamlib/rigctld mode string -> FlexRadio slice mode string.
MODE_MAP = {
    "USB": "USB", "LSB": "LSB", "CW": "CW", "CWR": "CW",
    "AM": "AM", "FM": "FM", "FMN": "NFM",
    "RTTY": "RTTY", "RTTYR": "RTTY",
    "PKTUSB": "DIGU", "PKTLSB": "DIGL", "PKTFM": "NFM",
    "DATA": "DIGU", "DIGU": "DIGU", "DIGL": "DIGL",
}


@dataclass
class Slice:
    index: int = 0
    in_use: bool = True
    freq_hz: int = 14074000
    mode: str = "USB"
    tx: bool = True          # is this the transmit slice? the amp keys band prep off tx=1
    txant: str = "ANT1"

    def status_line(self, handle: str = "0") -> str:
        # RF_frequency is MHz with 6 decimals, matching real SmartSDR output.
        return (
            f"S{handle}|slice {self.index} "
            f"in_use={1 if self.in_use else 0} "
            f"RF_frequency={self.freq_hz / 1_000_000:.6f} "
            f"mode={self.mode} "
            f"tx={1 if self.tx else 0} "
            f"txant={self.txant}"
        )


class Radio:
    def __init__(self, config: "Config") -> None:
        self.config = config
        self.slices: dict[int, Slice] = {0: Slice()}
        self.clients: set["ClientSession"] = set()
        self.amplifiers: dict[str, dict] = {}
        self.meters: dict[int, dict] = {}
        self.interlocks: dict[int, dict] = {}
        self._next_handle = 0x40000000  # object handles/stream ids start high, like SmartSDR
        self._next_meter = 1

    # --- object id allocation -------------------------------------------------
    def alloc_handle(self) -> int:
        h = self._next_handle
        self._next_handle += 0x01000000
        return h

    def alloc_meter_id(self) -> int:
        m = self._next_meter
        self._next_meter += 1
        return m

    # --- client registry ------------------------------------------------------
    def add_client(self, client: "ClientSession") -> None:
        self.clients.add(client)

    def remove_client(self, client: "ClientSession") -> None:
        self.clients.discard(client)

    # --- slice updates from the rig source -----------------------------------
    def update_slice(self, index: int = 0, *, freq_hz: int | None = None,
                     mode: str | None = None, tx: bool | None = None) -> None:
        sl = self.slices.setdefault(index, Slice(index=index))
        changed = False
        if freq_hz is not None and freq_hz != sl.freq_hz:
            sl.freq_hz = freq_hz
            changed = True
        if mode is not None:
            mapped = MODE_MAP.get(mode.upper(), mode.upper())
            if mapped != sl.mode:
                sl.mode = mapped
                changed = True
        if tx is not None and tx != sl.tx:
            sl.tx = tx
            changed = True
        if changed:
            log.debug("slice %d -> %.6f MHz %s tx=%d",
                      index, sl.freq_hz / 1e6, sl.mode, sl.tx)
            self.broadcast_slice(index)

    def broadcast_slice(self, index: int) -> None:
        sl = self.slices.get(index)
        if sl is None:
            return
        line = sl.status_line()
        for client in list(self.clients):
            if client.subscribed("slice"):
                client.send_line(line)

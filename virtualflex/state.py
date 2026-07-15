"""Shared radio state: slices, the transmit/interlock objects, and clients.

The object formats here mirror what a real FLEX-8600 emits (captured 2026-07-13),
because the PGXL is strict about them: it reads its band from the ``transmit``
object's ``freq`` (not the slice), so a minimal slice alone leaves it at "N/A".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config
    from .protocol import ClientSession

log = logging.getLogger("virtualflex.state")

# Normalize an incoming mode string (from the native K4 client) to a canonical
# FlexRadio slice mode.
MODE_MAP = {
    "USB": "USB", "LSB": "LSB", "CW": "CW", "CWR": "CW",
    "AM": "AM", "FM": "FM", "FMN": "NFM",
    "RTTY": "RTTY", "RTTYR": "RTTY",
    "PKTUSB": "DIGU", "PKTLSB": "DIGL", "PKTFM": "NFM",
    "DATA": "DIGU", "DIGU": "DIGU", "DIGL": "DIGL",
}

# A plausible GUI-client handle to own the slice (a real slice references the
# SmartSDR client that created it via client_handle=).
GUI_CLIENT_HANDLE = "0x39BEDD22"


@dataclass
class Slice:
    index: int = 0
    in_use: bool = True
    freq_hz: int = 14074000
    mode: str = "USB"
    tx: bool = True          # this is the transmit slice (static designation, not PTT)
    txant: str = "ANT1"

    @property
    def index_letter(self) -> str:
        return chr(ord("A") + self.index)  # slice 0 -> A, 1 -> B, ...

    def status_line(self, handle: str = "0") -> str:
        """Slice status modeled on a real FLEX-8600 slice (DSP-detail fields
        trimmed; identity/antenna/mode fields kept)."""
        return (
            f"S{handle}|slice {self.index} in_use={1 if self.in_use else 0} "
            f"sample_rate=24000 RF_frequency={self.freq_hz / 1_000_000:.6f} "
            f"client_handle={GUI_CLIENT_HANDLE} index_letter={self.index_letter} "
            f"rit_on=0 rit_freq=0 xit_on=0 xit_freq=0 rxant={self.txant} "
            f"mode={self.mode} wide=0 filter_lo=0 filter_hi=2900 step=100 "
            f"step_list=1,10,50,100,500,1000,2000,3000 agc_mode=med agc_threshold=25 "
            f"agc_off_level=10 pan=0x40000000 txant={self.txant} loopa=0 loopb=0 "
            f"qsk=0 dax=0 dax_clients=0 lock=0 tx={1 if self.tx else 0} active=1 "
            f"ant_list=ANT1,ANT2,RX_A,RX_B "
            f"mode_list=LSB,USB,AM,CW,DIGL,DIGU,SAM,FM,NFM,DFM,RTTY "
            f"rfgain=32 tx_ant_list=ANT1,ANT2"
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
        self.transmitting = False  # global TX state, surfaced via the interlock object

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

    def drop_all_clients(self) -> None:
        """Close every stack connection and clear their registrations. Called when
        the K4 goes absent: the stack sees the radio vanish (like a real Flex
        powering off) and each box reverts to its no-transceiver antenna."""
        for client in list(self.clients):
            client.close()
        self.clients.clear()
        self.amplifiers.clear()
        self.meters.clear()
        self.interlocks.clear()
        self._next_meter = 1

    def _send_to_slice_subs(self, line: str) -> None:
        for client in list(self.clients):
            if client.subscribed("slice"):
                client.send_line(line)

    # --- the transmit slice (what the amp follows) ---------------------------
    def tx_slice(self) -> Slice:
        for sl in self.slices.values():
            if sl.tx:
                return sl
        return self.slices[0]

    def transmit_status_line(self, handle: str = "0") -> str:
        """The `transmit` object. The PGXL reads its band from `freq=` here."""
        sl = self.tx_slice()
        return (
            f"S{handle}|transmit freq={sl.freq_hz / 1_000_000:.6f} rfpower=0 "
            f"tunepower=0 tune=0 tx_slice_mode={sl.mode} hwalc_enabled=0 inhibit=0 "
            f"dax=0 lo=100 hi=2900 tx_filter_changes_allowed=1 tx_antenna={sl.txant} "
            f"max_power_level=100"
        )

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
        # The amp follows the transmit object; send both so band + display track.
        self._send_to_slice_subs(sl.status_line())
        self._send_to_slice_subs(self.transmit_status_line())

    # --- transmit / interlock -------------------------------------------------
    def interlock_config_line(self) -> str:
        return ("S0|interlock acc_txreq_enable=0 rca_txreq_enable=0 acc_tx_enabled=1 "
                "tx1_enabled=1 tx2_enabled=1 tx3_enabled=1 tx_delay=0 acc_tx_delay=0 "
                "tx1_delay=0 tx2_delay=0 tx3_delay=0 acc_txreq_polarity=0 "
                "rca_txreq_polarity=0 timeout=0")

    def amp_client_handles(self) -> list[str]:
        """Connection handles of clients that registered as amplifiers — listed in
        the interlock's amplifier= field so each amp can recognize it should key."""
        return [f"0x{c.handle:08X}" for c in self.clients
                if getattr(c, "is_amplifier", False)]

    def interlock_status_line(self, state: str | None = None) -> str:
        """Interlock state, matching a real 8600. Idle=READY; a key runs
        READY -> PTT_REQUESTED -> TRANSMITTING, with tx_client_handle set and the
        engaged amp handles in amplifier= (what an amp needs to LAN-key), then
        UNKEY_REQUESTED -> READY on release."""
        if state is None:
            state = "TRANSMITTING" if self.transmitting else "READY"
        keyed = state in ("PTT_REQUESTED", "TRANSMITTING", "UNKEY_REQUESTED")
        txch = GUI_CLIENT_HANDLE if keyed else "0x00000000"
        source = "SW" if state in ("PTT_REQUESTED", "TRANSMITTING") else ""
        amps = (",".join(self.amp_client_handles())
                if state in ("TRANSMITTING", "UNKEY_REQUESTED") else "")
        return (f"S0|interlock tx_client_handle={txch} state={state} "
                f"reason= source={source} tx_allowed=1 amplifier={amps}")

    def set_transmit(self, tx: bool) -> None:
        if tx == self.transmitting:
            return
        self.transmitting = tx
        if tx:
            log.info("TX ON (keyed)")
            self._broadcast_interlock("PTT_REQUESTED")
            self._broadcast_interlock("TRANSMITTING")
        else:
            log.info("TX off")
            self._broadcast_interlock("UNKEY_REQUESTED")
            self._broadcast_interlock("READY")

    def _broadcast_interlock(self, state: str | None = None) -> None:
        line = self.interlock_status_line(state)
        for client in list(self.clients):
            client.send_line(line)  # sent to all clients, not gated on a subscription

    # --- radio object (sent on connect) --------------------------------------
    def radio_status_line(self) -> str:
        r = self.config.radio
        return (
            f"S0|radio slices=1 panadapters=1 lineout_gain=50 lineout_mute=0 "
            f"headphone_gain=0 headphone_mute=0 remote_on_enabled=0 pll_done=0 "
            f"freq_error_ppb=0 cal_freq=15.000000 tnf_enabled=0 "
            f"nickname={str(r['nickname']).replace(' ', '_')} callsign={r['callsign']} "
            f"binaural_rx=0 full_duplex_enabled=0 band_persistence_enabled=1 "
            f"rtty_mark_default=2125 backlight=50 daxiq_capacity=16 daxiq_available=16 "
            f"low_latency_digital_modes=0 mf_enable=1 auto_save=1 external_pa_allowed=1"
        )

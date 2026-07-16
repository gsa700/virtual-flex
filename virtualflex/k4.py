"""Native Elecraft K4/K4D network-CAT client.

A single connection to the K4's CAT port (9200). Enables auto-info (``AI2``) so
the K4 **pushes** ``FA/FB/FT/MD`` changes the instant they happen — dial spins
reach the stack event-driven, like a real Flex — with a slow poll kept only as
a resync fallback. PTT stays on the fast ``TQX`` poll (its latency floor is the
poll, and it must never depend on the push path). In split (``FT=1``) the
transmit VFO is B, so the stack must follow ``FB``; otherwise ``FA``.

AI state is per-connection on the K4, so ``AI2`` here never affects a logger's
own CAT session, and a reconnect re-arms it.

The K4 is addressed by IP (no per-connect DNS). If the cached IP stops
answering, one mDNS lookup relearns it (see :func:`mdns.resolve`) so DHCP
installs self-heal. Reconnects with exponential backoff so a powered-off radio
stays quiet on the network.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from . import mdns

log = logging.getLogger("virtualflex.k4")

# Elecraft MD codes -> Flex mode strings. Band/relay logic keys off frequency,
# so the exact mode only matters for display; map the common ones sensibly.
_MODE = {"1": "LSB", "2": "USB", "3": "CW", "4": "FM",
         "5": "AM", "6": "DIGU", "7": "CW", "9": "DIGL"}

TxCallback = Callable[[int, str], None]     # (tx_freq_hz, mode)
PttCallback = Callable[[bool], None]        # keyed?


class K4Client:
    # While the K4 is absent we retry the cached IP at a short, FIXED interval
    # (connecting to an IP is cheap and DNS-free), so the stack recovers within
    # seconds of the K4 finishing its boot — no exponential backoff to sit out.
    _CONNECT_TIMEOUT = 2.0    # bound each connect: a powered-off host makes the OS
                              # retransmit SYN for ~2 min otherwise, stalling recovery
    _RETRY_INTERVAL = 1.0     # steady reconnect poll while the K4 is unreachable
    _RECONNECT_DELAY = 1.0    # brief pause after a live link drops
    _MDNS_EVERY = 5           # re-resolve the IP every Nth failed try (catch DHCP changes)

    def __init__(self, *, ip: str, port: int = 9200, hostname: str | None = None,
                 ptt_interval: float = 0.003, freq_interval: float = 2.0,
                 stale_after: float = 3.0,
                 on_tx: TxCallback | None = None,
                 on_ptt: PttCallback | None = None) -> None:
        self.ip = ip
        self.port = port
        self.hostname = hostname            # for mDNS IP-refresh; None disables it
        self.ptt_interval = ptt_interval
        self.freq_interval = freq_interval
        self._stale_after = stale_after
        self.on_tx = on_tx or (lambda f, m: None)
        self.on_ptt = on_ptt or (lambda k: None)

        self._vfo_a: Optional[int] = None
        self._vfo_b: Optional[int] = None
        self._tx_vfo = 0
        self._mode = ""
        self._ptt = False
        self._last_emit: Optional[tuple[int, str]] = None

        self._connected = False
        self._connected_this_session = False
        self._last_rx = 0.0

    # ---- presence (consumed by the supervisor) -----------------------------
    def is_present(self) -> bool:
        """True while connected AND a valid response arrived recently."""
        if not self._connected:
            return False
        return (asyncio.get_running_loop().time() - self._last_rx) < self._stale_after

    @property
    def tx_freq_hz(self) -> Optional[int]:
        return self._vfo_b if self._tx_vfo == 1 else self._vfo_a

    # ---- lifecycle ----------------------------------------------------------
    async def run(self) -> None:
        fails = 0
        while True:
            self._connected_this_session = False
            try:
                await self._session()
            except (OSError, ConnectionError, asyncio.IncompleteReadError) as exc:
                log.debug("K4 session ended: %s", exc)
            self._connected = False
            if self._connected_this_session:
                fails = 0
                await asyncio.sleep(self._RECONNECT_DELAY)
                continue
            # absent: retry the cached IP at a steady, short interval. Re-resolve
            # via mDNS only occasionally, to catch a DHCP address change.
            fails += 1
            if self.hostname and fails % self._MDNS_EVERY == 0:
                new_ip = await self._refresh_ip()
                if new_ip and new_ip != self.ip:
                    log.info("K4 address changed %s -> %s (mDNS)", self.ip, new_ip)
                    self.ip = new_ip
                    continue
            await asyncio.sleep(self._RETRY_INTERVAL)

    async def _refresh_ip(self) -> str | None:
        if not self.hostname:
            return None
        try:
            return await mdns.resolve(self.hostname)
        except OSError as exc:
            log.debug("mDNS refresh failed: %s", exc)
            return None

    async def _session(self) -> None:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.ip, self.port), self._CONNECT_TIMEOUT)
        self._connected = True
        self._connected_this_session = True
        self._last_rx = asyncio.get_running_loop().time()
        log.info("K4 CAT connected to %s:%d", self.ip, self.port)
        try:
            await asyncio.gather(self._writer_loop(writer), self._reader_loop(reader))
        finally:
            writer.close()

    async def _writer_loop(self, writer: asyncio.StreamWriter) -> None:
        # AI2 arms push mode: the K4 volunteers FA/FB/FT/MD the moment they
        # change, so frequency follow is event-driven. The periodic FA/FB/FT/MD
        # below is only a slow RESYNC in case a push is lost or AI is reset.
        writer.write(b"AI2;FA;FB;FT;MD;TQX;")      # arm push mode + initial full read
        await writer.drain()
        every = max(1, round(self.freq_interval / self.ptt_interval))
        tick = 0
        while True:
            writer.write(b"TQX;")                  # fast PTT poll every cycle
            tick += 1
            if tick % every == 0:
                writer.write(b"FA;FB;FT;MD;")       # slow resync (pushes are the fast path)
            await writer.drain()
            await asyncio.sleep(self.ptt_interval)

    async def _reader_loop(self, reader: asyncio.StreamReader) -> None:
        buf = ""
        while True:
            data = await reader.read(512)
            if not data:
                raise ConnectionError("K4 closed the CAT connection")
            self._last_rx = asyncio.get_running_loop().time()
            buf += data.decode("ascii", "replace")
            while ";" in buf:
                stmt, _, buf = buf.partition(";")
                self._dispatch(stmt.strip())

    def _dispatch(self, stmt: str) -> None:
        try:
            if stmt.startswith("FA"):
                self._vfo_a = int(stmt[2:]); self._emit_tx()
            elif stmt.startswith("FB"):
                self._vfo_b = int(stmt[2:]); self._emit_tx()
            elif stmt.startswith("FT"):
                self._tx_vfo = int(stmt[2:3]); self._emit_tx()
            elif stmt.startswith("MD") and not stmt.startswith("MD$"):
                self._mode = _MODE.get(stmt[2:3], self._mode); self._emit_tx()
            elif stmt.startswith("TQ"):
                self._emit_ptt(stmt[2:3] == "1")
        except (ValueError, IndexError):
            log.debug("unparsable K4 statement: %r", stmt)

    def _emit_tx(self) -> None:
        freq = self.tx_freq_hz
        if not freq or freq <= 0 or not self._mode:
            return
        cur = (freq, self._mode)
        if cur != self._last_emit:
            self._last_emit = cur
            self.on_tx(freq, self._mode)

    def _emit_ptt(self, keyed: bool) -> None:
        if keyed != self._ptt:
            self._ptt = keyed
            self.on_ptt(keyed)

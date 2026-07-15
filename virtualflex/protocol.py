"""Per-connection FlexRadio command/status handling.

The amplifier connects and drives the exchange documented in FlexRadio's
"PowerGenius XL API" doc: after the ``V``/``H`` handshake it registers itself
(``amplifier create``), creates meters, creates an interlock, enables keepalive,
then subscribes to the slice subsystem. We ack each and stream slice status.

Wire framing:
    client -> radio:  C<seq>|<command><0x0D>
    radio  -> client: R<seq>|<hex>|<message>      (one reply per command)
                      S<handle>|<object> k=v ...  (async status)
                      V<ver> / H<hex>             (handshake, sent on connect)
"""
from __future__ import annotations

import asyncio
import logging
import re

from .state import Radio

log = logging.getLogger("virtualflex.protocol")

_LINE_SPLIT = re.compile(rb"[\r\n]+")


def parse_kv(tokens: list[str]) -> dict[str, str]:
    """Parse ``key=value`` tokens; bare tokens are ignored."""
    out: dict[str, str] = {}
    for tok in tokens:
        if "=" in tok:
            k, _, v = tok.partition("=")
            out[k] = v
    return out


class ClientSession:
    def __init__(self, radio: Radio, reader: asyncio.StreamReader,
                 writer: asyncio.StreamWriter) -> None:
        self.radio = radio
        self.reader = reader
        self.writer = writer
        self.handle = radio.alloc_handle()
        self.subscriptions: set[str] = set()
        self.keepalive = False
        self.is_amplifier = False  # set when this client registers via `amplifier create`
        self.client_banner: str | None = None  # e.g. the Antenna Genius sends "V4.1.16 AG"
        self.peer = writer.get_extra_info("peername")

    # --- helpers --------------------------------------------------------------
    def subscribed(self, obj: str) -> bool:
        return obj in self.subscriptions or "all" in self.subscriptions

    def send_line(self, line: str) -> None:
        if self.writer.is_closing():
            return
        log.debug("-> %s: %s", self.peer, line)  # trace what we emit (diagnostics)
        self.writer.write((line + "\n").encode("ascii", "replace"))

    def _ok(self, seq: str, message: str = "") -> None:
        self.send_line(f"R{seq}|0|{message}")

    def close(self) -> None:
        """Drop this connection; run()'s reader wakes on EOF and cleans up."""
        try:
            self.writer.close()
        except OSError:
            pass

    # --- lifecycle ------------------------------------------------------------
    async def run(self) -> None:
        self.radio.add_client(self)
        log.info("client connected: %s (handle 0x%08X)", self.peer, self.handle)
        # Handshake: the radio speaks first, then an initial state dump.
        self.send_line("V1.4.0.0")
        self.send_line(f"H{self.handle:08X}")
        self.send_line(self.radio.radio_status_line())
        self.send_line(self.radio.interlock_config_line())
        self.send_line(self.radio.interlock_status_line())  # valid PTT path from the start
        await self.writer.drain()

        buffer = b""
        try:
            while True:
                data = await self.reader.read(4096)
                if not data:
                    break
                buffer += data
                *lines, buffer = _LINE_SPLIT.split(buffer)
                for raw in lines:
                    if raw.strip():
                        self._handle_line(raw.decode("ascii", "replace"))
                await self.writer.drain()
        except (ConnectionResetError, asyncio.IncompleteReadError):
            pass
        finally:
            self.radio.remove_client(self)
            log.info("client disconnected: %s", self.peer)
            self.writer.close()

    # --- command dispatch -----------------------------------------------------
    def _handle_line(self, line: str) -> None:
        tag = line[:1]
        if tag == "V":
            # Client version banner (the Antenna Genius greets with "V4.1.16 AG").
            self.client_banner = line
            log.info("client %s banner: %s", self.peer, line)
            return
        if tag == "R":
            # Client reply/NAK. The AG sends "R0|1|" (code 1 = invalid command
            # format) when its v4 parser rejects a line we sent. Diagnostic only.
            log.debug("client %s reply/nak: %s", self.peer, line)
            return
        if tag not in ("C", "c"):
            log.warning("unexpected line from %s: %r", self.peer, line)
            return
        body = line[1:]
        if body[:1] in ("D", "d"):  # optional debug flag
            body = body[1:]
        seq, sep, command = body.partition("|")
        if not sep:
            log.warning("malformed command from %s: %r", self.peer, line)
            return
        self._dispatch(seq, command.strip())

    def _dispatch(self, seq: str, command: str) -> None:
        log.debug("recv <= C%s|%s", seq, command)  # full command trace for bring-up
        tokens = command.split()
        verb = tokens[0].lower() if tokens else ""

        if verb == "sub":
            self._cmd_sub(seq, tokens[1:])
        elif verb == "unsub":
            self._ok(seq)
        elif verb == "amplifier":
            self._cmd_amplifier(seq, tokens[1:])
        elif verb == "meter":
            self._cmd_meter(seq, tokens[1:])
        elif verb == "interlock":
            self._cmd_interlock(seq, tokens[1:])
        elif verb == "keepalive":
            self.keepalive = True
            self._ok(seq)
        elif verb == "ping":
            self._ok(seq)
        elif verb == "message":
            log.info("amp message from %s: %s", self.peer, command)
            self._ok(seq)
        elif verb in ("client", "info", "version"):
            self._ok(seq)
        else:
            # Permissive during bring-up: ack unknowns but log them so a capture
            # diff shows exactly what the PGXL sends that we don't yet model.
            log.warning("unhandled command from %s: C%s|%s", self.peer, seq, command)
            self._ok(seq)

    def _cmd_sub(self, seq: str, args: list[str]) -> None:
        obj = args[0].lower() if args else "all"
        self.subscriptions.add(obj)
        log.info("client %s subscribed: %s", self.peer, obj)
        self._ok(seq)
        # After acking, dump current state for the newly-subscribed object.
        if obj in ("slice", "tx", "all"):
            for index in sorted(self.radio.slices):
                self.send_line(self.radio.slices[index].status_line())
            self.send_line(self.radio.transmit_status_line())

    def _cmd_amplifier(self, seq: str, args: list[str]) -> None:
        if args and args[0].lower() == "create":
            kv = parse_kv(args[1:])
            handle = self.radio.alloc_handle()
            self.radio.amplifiers[f"0x{handle:08X}"] = kv
            self.is_amplifier = True  # so our conn handle appears in interlock amplifier=
            log.info("amplifier registered: %s", kv)
            # FLEX returns the new object's handle as the response message.
            self._ok(seq, f"0x{handle:08X}")
        else:
            self._ok(seq)

    def _cmd_meter(self, seq: str, args: list[str]) -> None:
        if args and args[0].lower() == "create":
            kv = parse_kv(args[1:])
            meter_id = self.radio.alloc_meter_id()
            self.radio.meters[meter_id] = kv
            log.info("meter created id=%d %s", meter_id, kv)
            self._ok(seq, str(meter_id))
        else:
            self._ok(seq)

    def _cmd_interlock(self, seq: str, args: list[str]) -> None:
        action = args[0].lower() if args else ""
        if action == "create":
            kv = parse_kv(args[1:])
            ilk_id = len(self.radio.interlocks) + 1
            self.radio.interlocks[ilk_id] = kv
            log.info("interlock created id=%d %s", ilk_id, kv)
            self._ok(seq, str(ilk_id))
        else:
            self._ok(seq)

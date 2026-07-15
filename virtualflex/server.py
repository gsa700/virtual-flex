"""TCP command/status server on the FlexRadio command port (4992).

The supervisor starts and stops this with the K4's presence. Stopping closes the
listener *and* drops every live stack connection, so the Genius stack sees the
radio disappear like a real Flex powering off.
"""
from __future__ import annotations

import asyncio
import logging

from .protocol import ClientSession
from .state import Radio

log = logging.getLogger("virtualflex.server")


class CommandServer:
    def __init__(self, radio: Radio) -> None:
        self.radio = radio
        self._server: asyncio.Server | None = None

    @property
    def port(self) -> int | None:
        if self._server and self._server.sockets:
            return self._server.sockets[0].getsockname()[1]
        return None

    async def start(self, host: str, port: int) -> None:
        if self._server is not None:
            return
        # start_server begins accepting immediately; no serve_forever() needed.
        self._server = await asyncio.start_server(self._on_client, host, port)
        addrs = ", ".join(str(s.getsockname()) for s in self._server.sockets)
        log.info("command server listening on %s", addrs)

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        # Drop the client connections BEFORE wait_closed(): on 3.13+ wait_closed()
        # blocks until active connections finish, so closing them first avoids a
        # deadlock. This is also what severs the stack's links -> it sees us gone.
        self.radio.drop_all_clients()
        try:
            await self._server.wait_closed()
        except OSError:
            pass
        self._server = None
        log.info("command server stopped; dropped all stack connections")

    async def _on_client(self, reader: asyncio.StreamReader,
                         writer: asyncio.StreamWriter) -> None:
        session = ClientSession(self.radio, reader, writer)
        try:
            await session.run()
        except Exception:  # noqa: BLE001 - never let one client kill the server
            log.exception("client handler crashed")

"""TCP command/status server on the FlexRadio command port (4992)."""
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

    async def start(self, host: str, port: int) -> None:
        self._server = await asyncio.start_server(self._on_client, host, port)
        addrs = ", ".join(str(s.getsockname()) for s in self._server.sockets)
        log.info("command server listening on %s", addrs)

    async def serve(self) -> None:
        assert self._server is not None, "call start() first"
        async with self._server:
            await self._server.serve_forever()

    async def _on_client(self, reader: asyncio.StreamReader,
                         writer: asyncio.StreamWriter) -> None:
        session = ClientSession(self.radio, reader, writer)
        try:
            await session.run()
        except Exception:  # noqa: BLE001 - never let one client kill the server
            log.exception("client handler crashed")

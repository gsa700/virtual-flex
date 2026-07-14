"""Presence supervisor — the v0.2 core.

Watches whether the K4 is present (via a health callback) and, with debounce,
brings the virtual radio ONLINE (broadcast discovery + serve the Genius stack)
or OFFLINE.

Going OFFLINE tears down discovery AND drops all stack connections, so the stack
sees the radio vanish exactly like a real Flex powering off — and the AGXL fails
over to Dummy Load, grounding antenna inputs for lightning safety. Keeping a fake
radio "present" while the K4 is off would defeat that failover, so this teardown
is a safety requirement, not polish.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

log = logging.getLogger("virtualflex.supervisor")

PresenceFn = Callable[[], bool]
Hook = Callable[[], Awaitable[None]]


class Supervisor:
    def __init__(self, *, is_present: PresenceFn,
                 go_online: Hook, go_offline: Hook,
                 present_after: float = 3.0, absent_after: float = 5.0,
                 poll_interval: float = 0.5) -> None:
        self.is_present = is_present
        self.go_online = go_online          # start discovery + serve the stack
        self.go_offline = go_offline        # stop discovery + drop all stack conns
        self.present_after = present_after   # K4 must be present this long before ONLINE
        self.absent_after = absent_after     # ...absent this long before OFFLINE
        self.poll_interval = poll_interval
        self._online = False

    @property
    def online(self) -> bool:
        return self._online

    async def run(self) -> None:
        pending_since: float | None = None   # when the pending transition started
        while True:
            now = asyncio.get_running_loop().time()
            present = self.is_present()
            if present and not self._online:
                pending_since = now if pending_since is None else pending_since
                if now - pending_since >= self.present_after:
                    log.info("K4 present -> ONLINE (advertising to the stack)")
                    await self.go_online()
                    self._online = True
                    pending_since = None
            elif not present and self._online:
                pending_since = now if pending_since is None else pending_since
                if now - pending_since >= self.absent_after:
                    log.warning("K4 absent -> OFFLINE (dropping stack; AGXL -> Dummy Load)")
                    await self.go_offline()
                    self._online = False
                    pending_since = None
            else:
                pending_since = None          # steady state — reset the debounce timer
            await asyncio.sleep(self.poll_interval)

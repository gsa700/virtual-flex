"""Rig source interface."""
from __future__ import annotations

from ..state import Radio


class RigSource:
    """Feeds the shared :class:`Radio` state with live rig data.

    Implementations run as a long-lived asyncio task, calling
    ``radio.update_slice(...)`` whenever frequency/mode/TX change.
    """

    def __init__(self, radio: Radio) -> None:
        self.radio = radio

    async def run(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

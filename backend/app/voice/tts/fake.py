"""A synthesizer that produces silence of a plausible length.

Enough to exercise the turn loop, barge-in and the sink without a vendor: the pipeline
only cares that audio arrives, that it stops when cleared, and roughly how long it lasts.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from ..frames import BYTES_PER_SECOND, FRAME_BYTES, SILENCE_BYTE
from . import TtsSession

_END = None
CHARS_PER_SECOND = 14.0  # roughly conversational pace


class FakeTtsSession:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def speak(self, text: str) -> None:
        frames = max(1, int(len(text) / CHARS_PER_SECOND * BYTES_PER_SECOND) // FRAME_BYTES)
        for _ in range(frames):
            await self._queue.put(bytes([SILENCE_BYTE]) * FRAME_BYTES)

    async def flush(self) -> None: ...

    async def clear(self) -> None:
        while not self._queue.empty():
            self._queue.get_nowait()

    async def audio(self) -> AsyncIterator[bytes]:
        while True:
            chunk = await self._queue.get()
            if chunk is _END:
                return
            yield chunk

    async def close(self) -> None:
        await self._queue.put(_END)


class FakeTts:
    async def connect(self) -> FakeTtsSession:
        return FakeTtsSession()


if TYPE_CHECKING:

    def _conforms() -> TtsSession:
        return FakeTtsSession()

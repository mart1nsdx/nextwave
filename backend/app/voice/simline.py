"""A phone line made of a script. No PSTN, no cost, no waiting.

Plays the counterparty's side as real mu-law energy — loud while they are speaking,
mu-law silence otherwise — so the local barge-in gate is exercised for real rather than
stubbed out. Pair it with voice/stt/fake.py driven by the same script and the whole turn
loop runs end to end in milliseconds.
"""

import asyncio
from collections.abc import AsyncIterator, Sequence

from .frames import FRAME_BYTES, FRAME_MS, SILENCE_BYTE, InboundFrame
from .stt.fake import ScriptedUtterance

# Alternating full-scale mu-law: unambiguously above any sane barge-in threshold.
VOICED = bytes([0x00, 0x80] * (FRAME_BYTES // 2))
SILENT = bytes([SILENCE_BYTE]) * FRAME_BYTES


class SimLine:
    """Implements both AudioSource and AudioSink, like the real transport does."""

    def __init__(
        self,
        script: Sequence[ScriptedUtterance],
        tail_ms: int = 2000,
        pace_s: float = 0.001,
    ) -> None:
        self._script = tuple(script)
        self._until_ms = max((u.end_ms for u in script), default=0) + tail_ms
        self._pace_s = pace_s
        self.played: list[bytes] = []
        self.clears = 0

    async def frames(self) -> AsyncIterator[InboundFrame]:
        for offset in range(FRAME_MS, self._until_ms + FRAME_MS, FRAME_MS):
            voiced = any(u.start_ms <= offset <= u.end_ms for u in self._script)
            yield InboundFrame(payload=VOICED if voiced else SILENT, offset_ms=offset)
            # Let the recognizer, the model and the synthesizer actually make progress.
            # Without a real yield the whole call would resolve inside one event-loop
            # tick and nothing downstream would ever be scheduled.
            await asyncio.sleep(self._pace_s)

    async def send_audio(self, payload: bytes) -> None:
        self.played.append(payload)

    async def clear(self) -> None:
        self.clears += 1
        self.played.clear()

    async def mark(self, name: str) -> None: ...

    @property
    def played_ms(self) -> int:
        return sum(len(chunk) for chunk in self.played) * 1000 // 8000

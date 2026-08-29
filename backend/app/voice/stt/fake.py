"""A recognizer that hears a script instead of a phone line.

This is how the pipeline is exercised: no network, no API key, no cost, no PSTN leg, and
the same result every run. AGENTS.md is explicit that tests never place a real call, so
every ugly case in docs/UGLY_CASES.md eventually arrives here as a script.

It is driven by the *audio clock*, not by wall time: events fire when a frame carrying
the right offset is fed. That means the timing logic downstream is exercised for real,
and a test can replay a two-minute call in a millisecond.
"""

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..events import FinalTranscript, PartialTranscript, SpeechStarted, SttEvent, UtteranceEnd
from ..frames import InboundFrame
from . import SttSession

_END = None


@dataclass(frozen=True, slots=True)
class ScriptedUtterance:
    """One thing the counterparty says, and when they say it.

    `is_endpoint=False` models the case that breaks naive agents: the recognizer settles
    the words but the speaker is only pausing mid-sentence. No UtteranceEnd is emitted,
    so the agent must not treat it as its turn.
    """

    text: str
    start_ms: int
    end_ms: int
    is_endpoint: bool = True


class FakeSttSession:
    """Replays a script against the offsets of the frames it is fed."""

    def __init__(self, script: Sequence[ScriptedUtterance]) -> None:
        self._timeline = _build_timeline(script)
        self._next = 0
        self._queue: asyncio.Queue[SttEvent | None] = asyncio.Queue()

    async def send(self, frame: InboundFrame) -> None:
        while self._next < len(self._timeline) and self._timeline[self._next][0] <= frame.offset_ms:
            await self._queue.put(self._timeline[self._next][1])
            self._next += 1

    async def events(self) -> AsyncIterator[SttEvent]:
        while True:
            event = await self._queue.get()
            if event is _END:
                return
            yield event

    async def close(self) -> None:
        await self._queue.put(_END)


class FakeStt:
    """Provider handing out a fresh session per call, all replaying the same script."""

    def __init__(self, script: Sequence[ScriptedUtterance]) -> None:
        self._script = tuple(script)

    async def connect(self) -> FakeSttSession:
        return FakeSttSession(self._script)


def _build_timeline(script: Sequence[ScriptedUtterance]) -> list[tuple[int, SttEvent]]:
    """Expand utterances into the event stream a real recognizer would produce.

    Partials are progressive word prefixes spread across the utterance, because that is
    what barge-in and live display actually consume — and because a fake that only ever
    emits finals would let a bug in partial handling ship.
    """
    timeline: list[tuple[int, SttEvent]] = []

    for utterance in script:
        timeline.append((utterance.start_ms, SpeechStarted(offset_ms=utterance.start_ms)))

        words = utterance.text.split()
        span = max(utterance.end_ms - utterance.start_ms, 1)
        for spoken in range(1, len(words) + 1):
            at = utterance.start_ms + span * spoken // len(words)
            timeline.append((at, PartialTranscript(text=" ".join(words[:spoken]), offset_ms=at)))

        timeline.append(
            (
                utterance.end_ms,
                FinalTranscript(
                    text=utterance.text,
                    offset_ms=utterance.start_ms,
                    end_offset_ms=utterance.end_ms,
                    is_endpoint=utterance.is_endpoint,
                ),
            )
        )
        if utterance.is_endpoint:
            timeline.append((utterance.end_ms, UtteranceEnd(offset_ms=utterance.end_ms)))

    # Stable, so events that share an offset keep the order a recognizer would emit them.
    return sorted(timeline, key=lambda entry: entry[0])


if TYPE_CHECKING:
    # Compile-time proof that the fake satisfies the contract. Without this the Protocol
    # is a comment: nothing else in the codebase ever assigns a session to that type.
    def _conforms(script: Sequence[ScriptedUtterance]) -> SttSession:
        return FakeSttSession(script)

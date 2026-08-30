"""Mu-law 8 kHz audio frames, and the transport contract the pipeline speaks.

The whole audio path is mu-law at 8 kHz end to end: Twilio Media Streams delivers it,
Deepgram accepts it for both recognition and synthesis, and Twilio plays it back. Nothing
resamples anything. That is deliberate — it removes a class of latency and quality bugs,
and it avoids `audioop`, which is deprecated in 3.12 and removed in 3.13.

AudioSource/AudioSink are the seam between the pipeline and the phone network. voice/
depends on these Protocols and never on Twilio, which is what lets the whole pipeline
run against a fake transport in tests with no PSTN leg and no cost.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

SAMPLE_RATE_HZ = 8000
BYTES_PER_SECOND = SAMPLE_RATE_HZ  # mu-law is one byte per sample
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE_HZ * FRAME_MS // 1000  # 160 — what Twilio sends per media event
SILENCE_BYTE = 0xFF  # mu-law zero, not 0x00


def _build_mulaw_decode_table() -> tuple[int, ...]:
    """G.711 mu-law byte -> signed 16-bit sample, precomputed for all 256 inputs.

    A 256-entry table instead of `audioop.ulaw2lin`: it is ten lines, has no import,
    and still exists on 3.13+, where audioop does not.
    """
    table: list[int] = []
    for encoded in range(256):
        value = ~encoded & 0xFF
        sign = value & 0x80
        exponent = (value >> 4) & 0x07
        mantissa = value & 0x0F
        magnitude = (((mantissa << 3) + 0x84) << exponent) - 0x84
        table.append(-magnitude if sign else magnitude)
    return tuple(table)


MULAW_DECODE = _build_mulaw_decode_table()


@dataclass(frozen=True, slots=True)
class InboundFrame:
    """One chunk of counterparty audio, with its position in the call.

    `offset_ms` is milliseconds since the start of the media stream. It is the anchor
    every commitment is eventually linked to (AGENTS.md invariant #3: a commitment with
    no audio offset is EVIDENCE_MISSING, never `verified`), so it is carried from the
    transport all the way through to the transcript rather than recomputed later.
    """

    payload: bytes
    offset_ms: int


class AudioSource(Protocol):
    """Counterparty audio arriving from the phone network."""

    @property
    def call_id(self) -> str:
        """Identifies this call in the logs.

        On the Protocol rather than passed in separately because it is not known until
        the transport has connected, and because three carriers are negotiated in
        parallel — logs that cannot be filtered by call are logs nobody can read.
        """
        ...

    @property
    def last_offset_ms(self) -> int:
        """Stream position of the most recent frame the transport has seen, in ms.

        The transport's own presentation timestamp, never a wall clock computed here.
        Read at the instant the agent's first audio for a turn goes out, it is what
        anchors an agent turn to when the agent actually spoke rather than to when the
        counterparty stopped — the difference between a commitment pointing at the
        moment it was agreed and one pointing at a moment before it existed.
        """
        ...

    def frames(self) -> AsyncIterator[InboundFrame]: ...


class AudioSink(Protocol):
    """Agent audio going back out to the phone network."""

    async def send_audio(self, payload: bytes) -> None:
        """Queue mu-law bytes for playback. Buffered by the transport, not by us."""

    async def clear(self) -> None:
        """Drop everything queued but not yet played. This is the barge-in cut."""

    async def mark(self, name: str) -> None:
        """Ask the transport to tell us when the audio queued so far has finished."""

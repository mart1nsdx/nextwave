"""Voice activity detection — two questions, two mechanisms, on purpose.

People tend to collapse VAD into one thing. It is two:

    "Did they *finish* speaking?"  -> we may reply
    "Did they *start* speaking?"   -> we must shut up

Turn end needs linguistic accuracy: a pause after "we can do it for eight thousand..."
is not the end of a sentence. The speech vendor's endpointer is much better at that than
an energy threshold, and it can afford a network round-trip because the counterparty has
already stopped talking. That question is answered by SttEvent.UtteranceEnd, not here.

Barge-in cannot afford that round-trip. If the agent is still talking 300 ms after being
interrupted, it sounds like a robot steamrolling a human, and the judge hears it. So the
"did they start?" question is answered locally, off the raw mu-law frames, in about one
frame time. Deepgram's SpeechStarted still arrives later and corroborates it; it is not
what triggers the cut.

This module is pure: no I/O, no async, no clock. Feed it bytes, it answers.
"""

import math

from pydantic import BaseModel, Field

from app.config import Settings

from .frames import BYTES_PER_SECOND, MULAW_DECODE


class VadSettings(BaseModel):
    """Tunables for both questions. Constructible with no environment, for tests."""

    model_config = {"frozen": True}

    endpointing_ms: int = Field(default=100, ge=10)
    utterance_end_ms: int = Field(default=1000, ge=100)
    barge_in_enabled: bool = True
    barge_in_rms_threshold: float = Field(default=1800.0, gt=0)
    barge_in_min_ms: int = Field(default=300, ge=0)
    min_silence_before_reply_ms: int = Field(default=250, ge=0)

    @classmethod
    def from_settings(cls, settings: Settings) -> "VadSettings":
        return cls(
            endpointing_ms=settings.vad_endpointing_ms,
            utterance_end_ms=settings.vad_utterance_end_ms,
            barge_in_enabled=settings.vad_barge_in_enabled,
            barge_in_rms_threshold=settings.vad_barge_in_rms_threshold,
            barge_in_min_ms=settings.vad_barge_in_min_ms,
            min_silence_before_reply_ms=settings.vad_min_silence_before_reply_ms,
        )


def frame_rms(payload: bytes) -> float:
    """Root-mean-square of a mu-law frame, in int16 units."""
    if not payload:
        return 0.0
    total = 0
    for byte in payload:
        sample = MULAW_DECODE[byte]
        total += sample * sample
    return math.sqrt(total / len(payload))


class EnergyVad:
    """Latching energy gate: fires once enough *consecutive* voiced audio has arrived.

    The consecutive requirement is what keeps a cough, a door, or a burst of line noise
    from cutting the agent off mid-sentence. A single loud frame is not an interruption;
    300 ms of sustained, speech-level energy is.
    """

    def __init__(self, settings: VadSettings) -> None:
        self._settings = settings
        self._voiced_ms = 0.0
        self._fired = False

    @property
    def voiced_ms(self) -> float:
        """How much consecutive voiced audio is currently accumulated. For logging."""
        return self._voiced_ms

    def feed(self, payload: bytes) -> bool:
        """Push one frame. True on the transition into speech, and only on that frame.

        Latches so a caller draining a queue of frames sees the interruption once, not
        once per frame for as long as the counterparty keeps talking.
        """
        if not self._settings.barge_in_enabled or not payload:
            return False

        if frame_rms(payload) >= self._settings.barge_in_rms_threshold:
            self._voiced_ms += len(payload) * 1000 / BYTES_PER_SECOND
        else:
            self._voiced_ms = 0.0
            self._fired = False

        if self._voiced_ms >= self._settings.barge_in_min_ms and not self._fired:
            self._fired = True
            return True
        return False

    def reset(self) -> None:
        """Forget accumulated energy. Call when the agent starts a new turn."""
        self._voiced_ms = 0.0
        self._fired = False

"""What the recognizer tells the pipeline, normalised across providers.

Every provider reports roughly these four things under different names. Normalising
here is what makes STT_PROVIDER a one-line change: voice/session.py reacts to these
types and never to a vendor's JSON.

Every event carries `offset_ms` — milliseconds since the start of the stream — because
the evidence chain needs to say *when* on the call something was said, not just that it
was said (AGENTS.md invariant #3).
"""

from dataclasses import dataclass

# These are audio plumbing, not business vocabulary, so they live here rather than in
# domain/. domain/ holds Operation, Quote, Commitment, Mandate — things a dispatcher
# would recognise. A partial transcript is not one of those.


@dataclass(frozen=True, slots=True)
class SpeechStarted:
    """The recognizer believes the counterparty began speaking."""

    offset_ms: int


@dataclass(frozen=True, slots=True)
class PartialTranscript:
    """Interim text. May still change — never act on it, only display or barge-in on it."""

    text: str
    offset_ms: int


@dataclass(frozen=True, slots=True)
class FinalTranscript:
    """Text the recognizer will not revise.

    `is_endpoint` is the vendor's own end-of-turn call (Deepgram's `speech_final`). A
    final transcript without it means "these words are settled, but they may still be
    mid-sentence" — which is not permission to answer.
    """

    text: str
    offset_ms: int
    end_offset_ms: int
    is_endpoint: bool


@dataclass(frozen=True, slots=True)
class UtteranceEnd:
    """The counterparty stopped talking. This is what releases the agent to reply."""

    offset_ms: int


SttEvent = SpeechStarted | PartialTranscript | FinalTranscript | UtteranceEnd

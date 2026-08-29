"""Shared vocabulary for the call-evidence and recap path.

Types only. No behaviour, no I/O, no decisions. If a function here would need to know
whether something is *allowed*, it belongs in policy/ instead (AGENTS.md invariant #1).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class CallDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CallStatus(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"
    FAILED = "failed"


class TranscriptTrack(StrEnum):
    """Which leg of the call the audio came from. Twilio labels these on Media Streams."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class Speaker(StrEnum):
    CALLER = "caller"
    AGENT = "agent"
    UNKNOWN = "unknown"


class CallCase(BaseModel):
    """One auditable case per Twilio call. Not a booking and not a commitment."""

    call_sid: str
    direction: CallDirection
    status: CallStatus = CallStatus.ACTIVE
    from_number: str | None = None
    to_number: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class TranscriptEvent(BaseModel):
    """One append-only unit of speech-to-text evidence.

    ``audio_offset_ms`` is the anchor a commitment links back to (AGENTS.md invariant #3):
    a commitment with no offset is EVIDENCE_MISSING, never ``verified``. ``event_key`` is
    the idempotency key — a redelivered frame must not create a second row (#7).
    """

    call_sid: str
    event_key: str
    track: TranscriptTrack
    speaker: Speaker = Speaker.UNKNOWN
    sequence_number: int = Field(ge=0)
    audio_offset_ms: int = Field(ge=0)
    text: str
    is_final: bool = False


def build_event_key(call_sid: str, track: TranscriptTrack, sequence_number: int) -> str:
    """Deterministic idempotency key for a transcript event.

    Deterministic on purpose: if OpenAI or Twilio redelivers the same segment, the key
    is identical and the store's insert becomes a no-op (AGENTS.md invariant #7).
    """

    return f"{call_sid}:{track.value}:{sequence_number}"


class Recap(BaseModel):
    """The negotiation, distilled. Content produced by a model — evidence, never authority.

    A later policy check reads this; it does not act on it directly.
    """

    call_sid: str
    summary: str
    key_points: list[str] = Field(default_factory=list)
    quoted_prices: list[str] = Field(default_factory=list)
    names: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    objections: list[str] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)
    model: str = ""
    generated_at: datetime | None = None


class RecapDeliveryStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class RecapDelivery(BaseModel):
    """Outcome of emailing the recap. ``SENT`` is the gate a policy step waits on before
    it lets a commitment reach COMMITTED (AGENTS.md invariant #3)."""

    call_sid: str
    status: RecapDeliveryStatus = RecapDeliveryStatus.PENDING
    to_email: str | None = None
    provider_message_id: str | None = None
    error: str | None = None
    sent_at: datetime | None = None


class BriefAction(BaseModel):
    """One thing the agent did on the call, anchored to when it happened."""

    audio_offset_ms: int = Field(ge=0)
    description: str


class BriefMention(BaseModel):
    """One relevant thing that was said — a price, a name, a condition, an objection."""

    audio_offset_ms: int = Field(ge=0)
    speaker: Speaker = Speaker.UNKNOWN
    detail: str


class CallBrief(BaseModel):
    """Structured log of actions taken and things mentioned. The 'report' for the dashboard."""

    call_sid: str
    actions: list[BriefAction] = Field(default_factory=list)
    mentions: list[BriefMention] = Field(default_factory=list)
    model: str = ""
    generated_at: datetime | None = None


class RecapContext(BaseModel):
    """Everything the recap model is allowed to know beyond the transcript itself.

    Kept explicit so nothing leaks in silently. The mandate is passed for *reference in
    the summary* only — the model never decides whether it was respected.
    """

    operation_ref: str | None = None
    mandate_summary: str | None = None
    carriers: list[str] = Field(default_factory=list)

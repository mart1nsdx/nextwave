"""Shared vocabulary for the call-evidence and recap path.

Types only. No behaviour, no I/O, no decisions. If a function here would need to know
whether something is *allowed*, it belongs in policy/ instead (AGENTS.md invariant #1).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from .security import CostComponent, Mandate, ReasonCode


class CallDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CallStatus(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"
    FAILED = "failed"


class CallPhase(StrEnum):
    """Which conversation this is. Set by market/, never inferred by the model.

    RFQ and AWARD are separate for the reason in AGENTS.md invariant #5: several carriers
    may hold confirmed offers at once, but only one call may close. A phase the model
    could talk itself into is not a phase.

    Lives in domain/ rather than agent/ because telephony/ needs the enum to bind a call
    to its case, and telephony/ may not import agent/ (tests/test_layering.py).
    """

    RFQ = "rfq"
    AWARD = "award"
    RENEGOTIATION = "renegotiation"
    INBOUND = "inbound"


class HandoffReason(StrEnum):
    """Deterministic categories that may justify involving a human."""

    DIRECT_REQUEST = "direct_request"
    OUTSIDE_MANDATE = "outside_mandate"
    AMBIGUOUS_CRITICAL_TERM = "ambiguous_critical_term"
    CONFLICTING_INFORMATION = "conflicting_information"
    POLICY_FAILURE = "policy_failure"
    TECHNICAL_FAILURE = "technical_failure"


class HandoffStatus(StrEnum):
    PROPOSED = "proposed"
    AUTHORIZED = "authorized"
    CALLER_ON_HOLD = "caller_on_hold"
    HUMAN_DIALING = "human_dialing"
    CONNECTED = "connected"
    DECLINED = "declined"
    FAILED = "failed"
    COMPLETED = "completed"


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


class HandoffRequest(BaseModel):
    """An auditable request to transfer a live call, never a commitment."""

    handoff_id: UUID
    call_sid: str
    reason: HandoffReason
    evidence_offset_ms: int = Field(ge=0)
    note: str = Field(min_length=1, max_length=500)
    status: HandoffStatus = HandoffStatus.PROPOSED
    conference_name: str | None = None
    operator_call_sid: str | None = None
    created_at: datetime | None = None


class HandoffEvent(BaseModel):
    """Append-only lifecycle evidence for a HandoffRequest."""

    event_key: str
    handoff_id: UUID
    status: HandoffStatus
    detail: str | None = None
    created_at: datetime | None = None


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


def anchor_is_evidenced(offset_ms: int | None, anchored_offsets: frozenset[int]) -> bool:
    """Is this anchor a real moment in the call, or a number someone produced?

    Pure and total, so the answer cannot depend on a model, a clock, or the network. The
    caller supplies ``anchored_offsets`` from the persisted transcript; membership is the
    whole test. ``None`` is honest ignorance and fails, but so does any offset the ledger
    never recorded — a plausible ``12345`` is no more evidence than ``0`` is. Absence and
    fabrication get the same answer because they are the same failure: an affirmation
    nobody can point at (AGENTS.md invariants #3 and #8).
    """

    return offset_ms is not None and offset_ms in anchored_offsets


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
    agreement_candidates: list[AgreementCandidate] = Field(default_factory=list)
    model: str = ""
    generated_at: datetime | None = None


class AgreementCandidate(BaseModel):
    """What the call appears to have agreed, anchored for deterministic policy review.

    This is deliberately not a Commitment. It is model-produced evidence which policy
    must validate against the mandate and the recap-delivery gate before anything can
    reach operation state.

    Superseded by ``Offer``: a model-extracted candidate is now persisted as an Offer with
    ``status='proposed'``, which policy promotes to ``'eligible'`` or ``'rejected'`` with a
    ``reason_code``. Kept until the remaining readers move over; do not build on it.
    """

    counterparty: str | None = None
    terms: str
    mandate_reference: str | None = None
    audio_offset_ms: int | None = Field(default=None, ge=0)
    """Where in the call the affirmation was heard, or ``None`` if nothing anchors it.

    Nullable on purpose. This model is handed to OpenAI as a structured-output response
    schema, so it is the extractor's entire vocabulary: a required integer leaves no way
    to say "no turn anchors this", and the model fills the hole with a number it did not
    hear — usually ``0``. That is exactly the inference AGENTS.md invariant #8 forbids,
    and policy's evidence gate only rejects ``None``, so a fabricated offset would pass
    it. A number here is a claim, not proof; ``anchor_is_evidenced`` is the check.
    """


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


# --- The case spine -----------------------------------------------------------------
#
# Everything above this line is evidence about one phone call. Everything below is the
# business case that call belongs to: the operation being run, the carriers solicited,
# the offers heard, and the audit trail of what the system did about them.
#
# Mandate and QuoteProposal already live in domain/security.py and are reused as-is.


class OperationPhase(StrEnum):
    """Where the operation is in its life. Advanced by market/, never by the model."""

    DRAFT = "draft"
    SOLICITING = "soliciting"
    AWARDING = "awarding"
    AWARDED = "awarded"
    FAILED = "failed"
    CLOSED = "closed"


class RfqPhase(StrEnum):
    """AGENTS.md invariant #5: soliciting and awarding are different phases, and only one
    RFQ per operation may be in either at a time."""

    SOLICITING = "soliciting"
    AWARDING = "awarding"
    AWARDED = "awarded"
    FAILED = "failed"


class OfferStatus(StrEnum):
    """PROPOSED is what a call may produce. Everything past it is set by policy/."""

    PROPOSED = "proposed"
    ELIGIBLE = "eligible"
    REJECTED = "rejected"
    ACCEPTED = "accepted"
    EXPIRED = "expired"


class CommitmentState(StrEnum):
    """UNKNOWN is a first-class outcome, not an error: an official email that timed out
    after dispatch may have begun is never re-sent and never claimed (ugly case 10)."""

    PREPARED = "prepared"
    RECAP_SENT = "recap_sent"
    COMMITTED = "committed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class AuditSubjectType(StrEnum):
    CALL = "call"
    HANDOFF = "handoff"
    OFFER = "offer"
    COMMITMENT = "commitment"
    RFQ = "rfq"


class AuditEventKind(StrEnum):
    """What the system did. Never what somebody said — that is a TranscriptEvent."""

    GUARD_DIRECTIVE = "guard_directive"
    POLICY_DECISION = "policy_decision"
    PROPOSAL_RECORDED = "proposal_recorded"
    ESCALATION_REQUESTED = "escalation_requested"
    CLARIFICATION_ASKED = "clarification_asked"
    MESSAGE_SENT = "message_sent"
    STATE_TRANSITION = "state_transition"


class Operation(BaseModel):
    """The shipment leg being run. The business case a call belongs to."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str = Field(min_length=1)
    reference: str = Field(min_length=1)
    container_number: str | None = None
    origin: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    eta: datetime | None = None
    phase: OperationPhase = OperationPhase.DRAFT
    created_at: datetime | None = None


class Carrier(BaseModel):
    """A trucking company. ``is_verified`` is prior knowledge, never something a caller
    can assert about itself on the phone."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    is_verified: bool = False
    created_at: datetime | None = None


class CarrierContact(BaseModel):
    """One reachable human at a carrier. ``phone_e164`` is globally unique, which is what
    makes an inbound number resolvable at all."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    carrier_id: UUID
    display_name: str | None = None
    phone_e164: str = Field(min_length=1)
    email: str | None = None
    created_at: datetime | None = None


class Rfq(BaseModel):
    """One quote-gathering round against one mandate version. Creates no obligation."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    operation_id: UUID
    mandate_id: UUID
    phase: RfqPhase = RfqPhase.SOLICITING
    created_at: datetime | None = None


class Offer(BaseModel):
    """A quote heard on a call, persisted exactly as heard.

    An Offer is not a commitment and not an edit. A later utterance with a different price
    is a *new* Offer with its own ``proposal_id`` and timestamp; nothing overwrites an
    earlier one (AGENTS.md invariant #4). ``status`` starts at PROPOSED and is only moved
    by policy/, which records why in ``reason_code``.
    """

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    rfq_id: UUID
    carrier_id: UUID
    carrier_contact_id: UUID
    call_id: UUID
    proposal_id: str = Field(min_length=1)
    source_event_id: str = Field(min_length=1)
    components: tuple[CostComponent, ...] = Field(min_length=1)
    cost_is_final: bool = False
    pickup_at: datetime | None = None
    equipment: str | None = None
    valid_until: datetime | None = None
    transcript_anchor_ms: int | None = Field(default=None, ge=0)
    carrier_confirmed_exact_recap: bool = False
    confirmed_at: datetime | None = None
    status: OfferStatus = OfferStatus.PROPOSED
    reason_code: ReasonCode | None = None
    created_at: datetime | None = None


class AuditEvent(BaseModel):
    """Append-only evidence of what the *system* did, keyed on ``event_key``.

    The dividing line against TranscriptEvent is deliberate and load-bearing: a transcript
    event is evidence of what was said, an audit event is evidence of what was done. If a
    row would be a quote of a human, it does not belong here.
    """

    model_config = ConfigDict(frozen=True)

    event_key: str = Field(min_length=1)
    subject_type: AuditSubjectType
    subject_id: str = Field(min_length=1)
    kind: AuditEventKind
    call_id: UUID | None = None
    from_state: str | None = None
    to_state: str | None = None
    reason_code: str | None = None
    audio_offset_ms: int | None = Field(default=None, ge=0)
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class CallBinding(BaseModel):
    """Everything a live call needs to know about which case it belongs to.

    Resolved once, before the session is built. Frozen because a counterparty must
    never be able to move a call to a different operation mid-conversation.
    """

    model_config = ConfigDict(frozen=True)

    call_id: UUID
    call_sid: str
    operation: Operation
    mandate: Mandate
    phase: CallPhase
    carrier: Carrier | None = None
    carrier_contact: CarrierContact | None = None

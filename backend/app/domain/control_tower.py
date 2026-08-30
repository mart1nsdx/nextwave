"""Read models and command contracts for the operator control tower.

These models describe information crossing the dashboard boundary. They contain no
authorization, persistence, or vendor behavior: a caller cannot turn a value in this
module into a booking without going through policy and market.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from .security import FxSnapshot, Mandate, TrustedSessionIdentity

__all__ = [
    "ActivationRequest",
    "Assignment",
    "AwardRequest",
    "BotConfiguration",
    "CallEvidence",
    "CallSummary",
    "CarrierCandidate",
    "CommandResult",
    "CommitmentSummary",
    "ConnectedAgent",
    "EvidencePointer",
    "MandateSummary",
    "OfferComparison",
    "OperationSummary",
    "OperationConfiguration",
    "OperationWorkspace",
    "PolicyDecisionSummary",
    "ReadinessCheck",
    "RfqPhase",
    "RfqSummary",
    "SourceSignal",
    "TimelineEvent",
    "TranscriptLine",
]


class RfqPhase(StrEnum):
    READY = "ready"
    OPEN = "open"
    AWARDING = "awarding"
    CLOSED = "closed"


class CommitmentState(StrEnum):
    NONE = "none"
    VERBAL = "verbal"
    RECAP_SENT = "recap_sent"
    COMMITTED = "committed"
    RESOURCED = "resourced"
    DOCUMENTED = "documented"
    EXECUTED = "executed"
    RECAP_FAILED = "recap_failed"


class SourceSignal(BaseModel):
    """A signal presented with source metadata instead of implied certainty."""

    label: str
    source: str
    status: str
    occurred_at: datetime
    is_demo: bool = False


class OperationSummary(BaseModel):
    """The one-line operational decision context used by the work queue."""

    id: str
    reference: str
    client_name: str
    container_number: str
    route: str
    stage: str
    attention: str
    days_remaining: int | None = None
    next_action: str
    source_freshness: str
    source_is_demo: bool = False


class TimelineEvent(BaseModel):
    label: str
    status: str
    source: str
    occurred_at: datetime | None = None
    is_current: bool = False
    is_demo: bool = False


class ReadinessCheck(BaseModel):
    label: str
    status: str
    detail: str
    is_ready: bool
    source: str


class MandateSummary(BaseModel):
    version: int
    cap_amount_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    pickup_window: str
    status: str
    authorized_actions: list[str]


class CarrierCandidate(BaseModel):
    id: str
    name: str
    reliability_percent: int = Field(ge=0, le=100)
    is_vetted: bool
    rationale: str


class OfferComparison(BaseModel):
    id: str
    carrier_id: str
    carrier_name: str
    freight_amount_minor: int = Field(ge=0)
    expected_total_amount_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    pickup_window: str
    reliability_percent: int = Field(ge=0, le=100)
    status: str
    rationale: str
    is_recommended: bool = False
    evidence_call_id: str | None = None


class RfqSummary(BaseModel):
    id: str
    phase: RfqPhase
    carrier_ids: list[str] = Field(default_factory=list)
    offers: list[OfferComparison] = Field(default_factory=list)


class CommitmentSummary(BaseModel):
    state: CommitmentState
    carrier_name: str | None = None
    recap_status: str | None = None
    evidence_available: bool = False


class Assignment(BaseModel):
    carrier_name: str
    driver_name: str
    driver_phone: str
    vehicle_plate: str
    carta_porte_status: str
    evidence_call_id: str | None = None


class ConnectedAgent(BaseModel):
    name: str
    role: str
    relationship: str
    status: str
    is_demo: bool = False


class CallSummary(BaseModel):
    id: str
    operation_id: str
    carrier_name: str
    direction: str
    status: str
    started_at: datetime
    duration_seconds: int = Field(ge=0)
    summary: str
    has_evidence: bool
    is_demo: bool = False


class OperationWorkspace(BaseModel):
    """Everything required to render one auditable operation without direct database access."""

    model_config = ConfigDict(frozen=True)

    id: str
    reference: str
    client_name: str
    container_number: str
    bill_of_lading: str
    cargo_description: str
    weight_kg: int = Field(ge=0)
    route: str
    ocean_carrier: str
    last_free_day: str | None = None
    days_remaining: int | None = None
    stage: str
    attention: str
    next_action: str
    signals: list[SourceSignal]
    timeline: list[TimelineEvent]
    readiness: list[ReadinessCheck]
    mandate: MandateSummary
    carrier_candidates: list[CarrierCandidate]
    rfq: RfqSummary
    commitment: CommitmentSummary
    assignment: Assignment | None = None
    connected_agents: list[ConnectedAgent]
    escalations: list[str] = Field(default_factory=list)
    is_demo: bool = False


class TranscriptLine(BaseModel):
    offset_ms: int = Field(ge=0)
    speaker: str
    text: str
    is_relevant: bool = False


class EvidencePointer(BaseModel):
    recording_id: str
    audio_offset_ms: int = Field(ge=0)
    transcript_event_id: str
    audio_url: str | None = None


class PolicyDecisionSummary(BaseModel):
    verdict: str
    reason_code: str
    decided_at: datetime


class CallEvidence(BaseModel):
    call: CallSummary
    call_brief: list[str]
    transcript: list[TranscriptLine]
    policy_decisions: list[PolicyDecisionSummary]
    recap_status: str
    evidence: EvidencePointer | None = None
    is_demo: bool = False


class ActivationRequest(BaseModel):
    carrier_ids: list[str] = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=200)


class AwardRequest(BaseModel):
    offer_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=200)


class CommandResult(BaseModel):
    operation_id: str
    rfq_id: str
    outcome: str
    message: str
    phase: RfqPhase
    is_demo: bool = False


class BotConfiguration(BaseModel):
    """Presentation preferences that never grant the bot additional authority."""

    model_config = ConfigDict(frozen=True)

    agent_name: str = Field(min_length=1)
    agent_role: str = Field(min_length=1)
    primary_language: str = Field(min_length=2)
    fallback_language: str = Field(min_length=2)
    recap_channel: str = Field(min_length=1)


class OperationConfiguration(BaseModel):
    """Human-owned security and communication settings for one operation."""

    model_config = ConfigDict(frozen=True)

    operation_id: str
    bot: BotConfiguration
    mandate: Mandate
    fx_snapshots: list[FxSnapshot]
    trusted_session: TrustedSessionIdentity
    is_demo: bool = False

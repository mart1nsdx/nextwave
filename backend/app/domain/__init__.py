"""Shared types. The only leaf package: Operation, Quote, Commitment, Mandate, events.

MAY IMPORT:  stdlib, pydantic. Nothing from app.
IMPORTED BY: everyone.

Types only — no behaviour, no I/O, no decisions. If a function here would need to know
whether something is *allowed*, it belongs in policy/ instead.
"""

from .company import BusinessType, CompanyProfile
from .control_tower import (
    ActivationRequest,
    Assignment,
    AwardRequest,
    BotConfiguration,
    CallEvidence,
    CallSummary,
    CarrierCandidate,
    CommandResult,
    CommitmentState,
    CommitmentSummary,
    ConnectedAgent,
    EvidencePointer,
    MandateSummary,
    OfferComparison,
    OperationConfiguration,
    OperationSummary,
    OperationWorkspace,
    PolicyDecisionSummary,
    ReadinessCheck,
    RfqPhase,
    RfqSummary,
    SourceSignal,
    TimelineEvent,
    TranscriptLine,
)
from .security import (
    CommitmentMode,
    CostComponent,
    FxSnapshot,
    Mandate,
    QuoteProposal,
    TrustedSessionIdentity,
)

__all__ = [
    "ActivationRequest",
    "Assignment",
    "AwardRequest",
    "BotConfiguration",
    "BusinessType",
    "CallEvidence",
    "CallSummary",
    "CarrierCandidate",
    "CommandResult",
    "CommitmentState",
    "CommitmentSummary",
    "CommitmentMode",
    "CompanyProfile",
    "ConnectedAgent",
    "EvidencePointer",
    "FxSnapshot",
    "CostComponent",
    "Mandate",
    "MandateSummary",
    "OfferComparison",
    "OperationSummary",
    "OperationConfiguration",
    "OperationWorkspace",
    "PolicyDecisionSummary",
    "ReadinessCheck",
    "QuoteProposal",
    "RfqPhase",
    "RfqSummary",
    "SourceSignal",
    "TimelineEvent",
    "TranscriptLine",
    "TrustedSessionIdentity",
]

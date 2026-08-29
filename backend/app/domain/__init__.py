"""Shared types. The only leaf package: Operation, Quote, Commitment, Mandate, events.

MAY IMPORT:  stdlib, pydantic. Nothing from app.
IMPORTED BY: everyone.

Types only — no behaviour, no I/O, no decisions. If a function here would need to know
whether something is *allowed*, it belongs in policy/ instead.
"""

from .company import BusinessType, CompanyProfile
from .security import (
    CommitmentMode,
    CostComponent,
    CostEvidence,
    FxSnapshot,
    Mandate,
    PolicyDecision,
    PolicyOutcome,
    PreparedCommitment,
    QuoteProposal,
    ReasonCode,
)

__all__ = [
    "BusinessType",
    "CommitmentMode",
    "CompanyProfile",
    "CostComponent",
    "CostEvidence",
    "FxSnapshot",
    "Mandate",
    "PolicyDecision",
    "PolicyOutcome",
    "PreparedCommitment",
    "QuoteProposal",
    "ReasonCode",
]

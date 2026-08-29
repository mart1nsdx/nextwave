"""Capability-separated tool surface around the deterministic reference monitor.

Only ``ProposalTools`` is safe to expose to a model. ``CommitmentCoordinator`` is a
server-side capability and intentionally has no ``commit`` or ``send`` method.
"""

import hashlib
from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.domain import (
    CommitmentMode,
    FxSnapshot,
    Mandate,
    PolicyDecision,
    PolicyOutcome,
    PreparedCommitment,
    QuoteProposal,
    ReasonCode,
)
from app.policy import evaluate_quote, require_preagreement_evidence, select_best


class ToolStatus(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


class ToolResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: ToolStatus
    proposal_id: str | None = None
    reason: ReasonCode | None = None


class AuditEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    event_type: str
    occurred_at: datetime
    subject_id: str
    detail: dict[str, str | int]


class ProposalTools:
    """The complete model-facing mutation surface: proposals, never authority."""

    def __init__(self) -> None:
        self._by_id: dict[str, QuoteProposal] = {}
        self._event_to_proposal: dict[str, str] = {}
        self._audit: list[AuditEvent] = []

    def propose_quote(self, proposal: QuoteProposal, *, now: datetime) -> ToolResult:
        previous = self._event_to_proposal.get(proposal.source_event_id)
        if previous is not None:
            if previous == proposal.proposal_id and self._by_id[previous] == proposal:
                return ToolResult(status=ToolStatus.DUPLICATE, proposal_id=previous)
            return ToolResult(status=ToolStatus.REJECTED, reason=ReasonCode.REPLAYED_EVENT)
        if proposal.proposal_id in self._by_id:
            return ToolResult(status=ToolStatus.REJECTED, reason=ReasonCode.CONFLICTING_STATE)

        self._by_id[proposal.proposal_id] = proposal
        self._event_to_proposal[proposal.source_event_id] = proposal.proposal_id
        self._audit.append(
            AuditEvent(
                event_id=proposal.source_event_id,
                event_type="QUOTE_PROPOSED",
                occurred_at=now,
                subject_id=proposal.proposal_id,
                detail={"call_id": proposal.source_call_id, "carrier_id": proposal.carrier_id},
            )
        )
        return ToolResult(status=ToolStatus.ACCEPTED, proposal_id=proposal.proposal_id)

    def read_proposal(self, proposal_id: str) -> QuoteProposal | None:
        return self._by_id.get(proposal_id)

    def proposals_for(self, operation_id: str) -> tuple[QuoteProposal, ...]:
        return tuple(p for p in self._by_id.values() if p.operation_id == operation_id)

    @property
    def audit_events(self) -> tuple[AuditEvent, ...]:
        return tuple(self._audit)


class CommitmentCoordinator:
    """Trusted orchestration for evaluate → rank → prepare → single claim.

    Claiming returns the exact immutable payload to an external adapter. The adapter may
    attempt delivery once; uncertain outcomes must be reconciled, never blindly retried.
    """

    def __init__(self, proposals: ProposalTools) -> None:
        self._proposals = proposals
        self._prepared: dict[str, PreparedCommitment] = {}
        self._payloads: dict[str, str] = {}
        self._claimed: set[str] = set()

    def evaluate_all(
        self,
        mandate: Mandate,
        fx: Mapping[str, FxSnapshot],
        *,
        now: datetime,
    ) -> list[tuple[QuoteProposal, PolicyDecision]]:
        results: list[tuple[QuoteProposal, PolicyDecision]] = []
        for proposal in self._proposals.proposals_for(mandate.operation_id):
            decision = evaluate_quote(mandate, proposal, fx, now=now)
            results.append((proposal, require_preagreement_evidence(mandate, proposal, decision)))
        return results

    def select(
        self,
        mandate: Mandate,
        fx: Mapping[str, FxSnapshot],
        *,
        now: datetime,
    ) -> QuoteProposal | None:
        return select_best(self.evaluate_all(mandate, fx, now=now))

    def prepare(
        self,
        *,
        commitment_id: str,
        proposal_id: str,
        mandate: Mandate,
        fx: Mapping[str, FxSnapshot],
        canonical_email: str,
        now: datetime,
        human_approval_id: str | None = None,
    ) -> PreparedCommitment:
        if commitment_id in self._prepared:
            raise ValueError(ReasonCode.CONFLICTING_STATE)
        proposal = self._proposals.read_proposal(proposal_id)
        if proposal is None:
            raise ValueError(ReasonCode.EVIDENCE_MISSING)
        decision = require_preagreement_evidence(
            mandate, proposal, evaluate_quote(mandate, proposal, fx, now=now)
        )
        if decision.outcome is not PolicyOutcome.ALLOW:
            raise ValueError(decision.reason)
        if self.select(mandate, fx, now=now) != proposal:
            raise ValueError(ReasonCode.CONFLICTING_STATE)
        if mandate.commitment_mode is CommitmentMode.HUMAN_ESCALATION and not human_approval_id:
            raise ValueError(ReasonCode.HUMAN_APPROVAL_REQUIRED)

        payload = _canonicalize_email(canonical_email)
        prepared = PreparedCommitment(
            commitment_id=commitment_id,
            proposal_id=proposal_id,
            mandate_id=mandate.mandate_id,
            mandate_version=mandate.version,
            canonical_payload_sha256=hashlib.sha256(payload.encode()).hexdigest(),
            prepared_at=now,
            expires_at=min(now + timedelta(seconds=30), proposal.valid_until),
            human_approval_id=human_approval_id,
        )
        self._prepared[commitment_id] = prepared
        self._payloads[commitment_id] = payload
        return prepared

    def claim_once(
        self,
        commitment_id: str,
        mandate: Mandate,
        fx: Mapping[str, FxSnapshot],
        *,
        now: datetime,
    ) -> str:
        prepared = self._prepared.get(commitment_id)
        if prepared is None:
            raise ValueError(ReasonCode.EVIDENCE_MISSING)
        if commitment_id in self._claimed:
            raise ValueError(ReasonCode.REPLAYED_EVENT)
        if now > prepared.expires_at:
            raise ValueError(ReasonCode.STALE_EVIDENCE)
        if (prepared.mandate_id, prepared.mandate_version) != (
            mandate.mandate_id,
            mandate.version,
        ):
            raise ValueError(ReasonCode.MANDATE_MISMATCH)
        selected = self.select(mandate, fx, now=now)
        if selected is None or selected.proposal_id != prepared.proposal_id:
            raise ValueError(ReasonCode.CONFLICTING_STATE)
        payload = self._payloads[commitment_id]
        if hashlib.sha256(payload.encode()).hexdigest() != prepared.canonical_payload_sha256:
            raise ValueError(ReasonCode.CONFLICTING_STATE)
        self._claimed.add(commitment_id)
        return payload


def _canonicalize_email(value: str) -> str:
    """Reject header injection and create one digest-stable representation."""
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if "\x00" in normalized or not normalized:
        raise ValueError("invalid canonical email")
    return normalized

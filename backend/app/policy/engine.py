"""Pure reference monitor. No model, network, persistence, or ambient clock access."""

from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal

from app.domain import (
    CostEvidence,
    FxSnapshot,
    Mandate,
    PolicyDecision,
    PolicyOutcome,
    QuoteProposal,
    ReasonCode,
)

_CENT = Decimal("0.01")


def _decision(
    mandate: Mandate,
    proposal: QuoteProposal,
    outcome: PolicyOutcome,
    reason: ReasonCode,
    cost: CostEvidence | None = None,
) -> PolicyDecision:
    return PolicyDecision(
        outcome=outcome,
        reason=reason,
        mandate_id=mandate.mandate_id,
        mandate_version=mandate.version,
        proposal_id=proposal.proposal_id,
        cost=cost,
    )


def evaluate_quote(
    mandate: Mandate,
    proposal: QuoteProposal,
    fx: Mapping[str, FxSnapshot],
    *,
    now: datetime,
    max_fx_age: timedelta = timedelta(hours=2),
) -> PolicyDecision:
    """Evaluate a proposal against immutable mandate and evidence snapshots."""
    if proposal.operation_id != mandate.operation_id:
        return _decision(mandate, proposal, PolicyOutcome.DENY, ReasonCode.MANDATE_MISMATCH)
    if not proposal.cost_is_final:
        return _decision(mandate, proposal, PolicyOutcome.ESCALATE, ReasonCode.INCOMPLETE_COST)
    if proposal.valid_until < now:
        return _decision(mandate, proposal, PolicyOutcome.DENY, ReasonCode.STALE_EVIDENCE)
    if not (mandate.pickup_not_before <= proposal.pickup_at <= mandate.pickup_not_after):
        return _decision(mandate, proposal, PolicyOutcome.DENY, ReasonCode.INVALID_WINDOW)
    if proposal.equipment not in mandate.allowed_equipment:
        return _decision(mandate, proposal, PolicyOutcome.DENY, ReasonCode.OUTSIDE_MANDATE)

    totals: dict[str, Decimal] = {}
    usd = Decimal(0)
    snapshot_ids: list[str] = []
    for component in proposal.components:
        totals[component.currency] = totals.get(component.currency, Decimal(0)) + component.amount
        if component.currency == "USD":
            usd += component.amount
            continue
        snapshot = fx.get(component.currency)
        if snapshot is None or snapshot.quote_currency != component.currency:
            return _decision(
                mandate, proposal, PolicyOutcome.ESCALATE, ReasonCode.FX_EVIDENCE_MISSING
            )
        if snapshot.observed_at > now or now - snapshot.observed_at > max_fx_age:
            return _decision(mandate, proposal, PolicyOutcome.DENY, ReasonCode.STALE_EVIDENCE)
        if mandate.fx_margin_bps is None:
            return _decision(
                mandate, proposal, PolicyOutcome.ESCALATE, ReasonCode.FX_EVIDENCE_MISSING
            )
        usd += component.amount * snapshot.usd_per_unit
        snapshot_ids.append(snapshot.snapshot_id)

    margin_bps = mandate.fx_margin_bps or 0
    unbuffered = usd.quantize(_CENT, rounding=ROUND_CEILING)
    buffered = (usd * (Decimal(1) + Decimal(margin_bps) / Decimal(10_000))).quantize(
        _CENT, rounding=ROUND_CEILING
    )
    evidence = CostEvidence(
        original_totals=totals,
        unbuffered_usd=unbuffered,
        margin_bps=margin_bps,
        buffered_usd=buffered,
        fx_snapshot_ids=tuple(sorted(set(snapshot_ids))),
    )
    if buffered > mandate.max_all_in_usd:
        return _decision(
            mandate, proposal, PolicyOutcome.ESCALATE, ReasonCode.OUTSIDE_MANDATE, evidence
        )
    return _decision(mandate, proposal, PolicyOutcome.ALLOW, ReasonCode.ALLOWED, evidence)


def require_preagreement_evidence(
    mandate: Mandate, proposal: QuoteProposal, decision: PolicyDecision
) -> PolicyDecision:
    """A model-interpreted yes is insufficient without exact, anchored recap evidence."""
    if decision.outcome is not PolicyOutcome.ALLOW:
        return decision
    if (
        not proposal.carrier_confirmed_exact_recap
        or proposal.confirmed_at is None
        or proposal.transcript_anchor_ms is None
    ):
        return _decision(mandate, proposal, PolicyOutcome.DENY, ReasonCode.EVIDENCE_MISSING)
    return decision


def select_best(decisions: list[tuple[QuoteProposal, PolicyDecision]]) -> QuoteProposal | None:
    """Lowest eligible buffered USD; deterministic tie-breaks from D32."""
    eligible = [
        (proposal, decision)
        for proposal, decision in decisions
        if decision.outcome is PolicyOutcome.ALLOW and decision.cost is not None
    ]
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda item: (
            item[1].cost.buffered_usd,  # type: ignore[union-attr]
            item[0].pickup_at,
            item[0].confirmed_at or datetime.max.replace(tzinfo=item[0].pickup_at.tzinfo),
            item[0].proposal_id,
        ),
    )[0]

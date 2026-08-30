"""Pure security-kernel checks for immutable mandates and call-derived proposals."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.domain import FxSnapshot, Mandate, QuoteProposal, TrustedSessionIdentity

__all__ = ["SecurityDecision", "evaluate_quote_proposal"]

_FX_MAX_AGE = timedelta(hours=2)
_USD = "USD"


@dataclass(frozen=True)
class SecurityDecision:
    verdict: str
    reason_code: str
    buffered_total_usd: Decimal | None = None


def evaluate_quote_proposal(
    mandate: Mandate,
    proposal: QuoteProposal,
    trusted_session: TrustedSessionIdentity,
    fx_snapshots: Mapping[str, FxSnapshot],
    now: datetime,
) -> SecurityDecision:
    """Evaluate evidence against human authorization without changing either input.

    The injected clock keeps freshness deterministic in tests. A proposal in a non-USD
    currency needs a fresh approved snapshot and an explicit human FX margin; missing
    evidence always fails closed.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if proposal.operation_id != mandate.operation_id:
        return SecurityDecision("deny", "OPERATION_MISMATCH")
    if proposal.carrier_id != trusted_session.trusted_carrier_id:
        return SecurityDecision("deny", "UNTRUSTED_CARRIER")
    if proposal.carrier_contact_id != trusted_session.trusted_contact_id:
        return SecurityDecision("deny", "UNTRUSTED_CONTACT")
    if not proposal.cost_is_final:
        return SecurityDecision("clarify", "COST_NOT_FINAL")
    if not proposal.carrier_confirmed_exact_recap:
        return SecurityDecision("clarify", "RECAP_NOT_CONFIRMED")
    if (
        proposal.pickup_at < mandate.pickup_not_before
        or proposal.pickup_at > mandate.pickup_not_after
    ):
        return SecurityDecision("deny", "PICKUP_OUTSIDE_WINDOW")
    if proposal.equipment not in mandate.allowed_equipment:
        return SecurityDecision("deny", "EQUIPMENT_NOT_ALLOWED")
    if proposal.valid_until < now:
        return SecurityDecision("deny", "QUOTE_EXPIRED")

    total_usd = Decimal("0")
    fx_exposed_usd = Decimal("0")
    for component in proposal.components:
        if component.currency == _USD:
            total_usd += component.amount
            continue
        if mandate.fx_margin_bps is None:
            return SecurityDecision("deny", "FX_MARGIN_REQUIRED")
        snapshot = fx_snapshots.get(component.currency)
        if snapshot is None:
            return SecurityDecision("deny", "FX_SNAPSHOT_MISSING")
        if snapshot.observed_at > now:
            return SecurityDecision("deny", "FX_SNAPSHOT_FROM_FUTURE")
        if now - snapshot.observed_at > _FX_MAX_AGE:
            return SecurityDecision("deny", "FX_SNAPSHOT_STALE")
        converted_component = component.amount * snapshot.usd_per_unit
        total_usd += converted_component
        fx_exposed_usd += converted_component

    margin = Decimal(mandate.fx_margin_bps or 0) / Decimal("10000")
    buffered_total = total_usd + (fx_exposed_usd * margin)
    if buffered_total > mandate.max_all_in_usd:
        return SecurityDecision("deny", "OUTSIDE_MANDATE", buffered_total)
    if mandate.commitment_mode.value == "human_escalation":
        return SecurityDecision("escalate", "HUMAN_ESCALATION_REQUIRED", buffered_total)
    return SecurityDecision("allow", "WITHIN_MANDATE", buffered_total)

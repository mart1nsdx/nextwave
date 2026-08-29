"""Deterministic reference-monitor oracles: pure, exact, and network-free."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.domain import (
    CommitmentMode,
    CostComponent,
    FxSnapshot,
    Mandate,
    PolicyOutcome,
    QuoteProposal,
    ReasonCode,
)
from app.policy import evaluate_quote, require_preagreement_evidence, select_best

NOW = datetime(2026, 8, 29, 18, 0, tzinfo=UTC)


def mandate(**changes: object) -> Mandate:
    values: dict[str, object] = {
        "mandate_id": "M-1",
        "version": 1,
        "owner_id": "owner-1",
        "operation_id": "OP-1",
        "max_all_in_usd": Decimal("1000"),
        "pickup_not_before": NOW + timedelta(days=1),
        "pickup_not_after": NOW + timedelta(days=3),
        "allowed_equipment": frozenset({"dry-van"}),
        "commitment_mode": CommitmentMode.AUTONOMOUS,
        "fx_margin_bps": 500,
    }
    values.update(changes)
    return Mandate(**values)  # type: ignore[arg-type]


def proposal(identifier: str = "P-1", **changes: object) -> QuoteProposal:
    values: dict[str, object] = {
        "proposal_id": identifier,
        "operation_id": "OP-1",
        "carrier_id": "carrier-1",
        "carrier_contact_id": "contact-1",
        "components": (CostComponent(name="all-in", amount=Decimal("900"), currency="USD"),),
        "cost_is_final": True,
        "pickup_at": NOW + timedelta(days=2),
        "equipment": "dry-van",
        "valid_until": NOW + timedelta(hours=1),
        "source_call_id": "CA-1",
        "source_event_id": f"EV-{identifier}",
        "transcript_anchor_ms": 1234,
        "carrier_confirmed_exact_recap": True,
        "confirmed_at": NOW,
    }
    values.update(changes)
    return QuoteProposal(**values)  # type: ignore[arg-type]


def test_price_above_cap_escalates() -> None:
    quote = proposal(
        components=(CostComponent(name="all-in", amount=Decimal("1000.01"), currency="USD"),)
    )
    result = evaluate_quote(mandate(), quote, {}, now=NOW)
    assert (result.outcome, result.reason) == (PolicyOutcome.ESCALATE, ReasonCode.OUTSIDE_MANDATE)


def test_comprehensive_cost_counts_every_component() -> None:
    quote = proposal(
        components=(
            CostComponent(name="linehaul", amount=Decimal("850"), currency="USD"),
            CostComponent(name="fuel", amount=Decimal("151"), currency="USD"),
        )
    )
    assert evaluate_quote(mandate(), quote, {}, now=NOW).reason is ReasonCode.OUTSIDE_MANDATE


def test_non_usd_requires_fresh_fx_and_applies_margin_upward() -> None:
    quote = proposal(
        components=(CostComponent(name="all-in", amount=Decimal("10000"), currency="MXN"),)
    )
    assert evaluate_quote(mandate(), quote, {}, now=NOW).reason is ReasonCode.FX_EVIDENCE_MISSING
    snapshot = FxSnapshot(
        snapshot_id="FX-1",
        quote_currency="MXN",
        usd_per_unit=Decimal("0.05"),
        observed_at=NOW - timedelta(minutes=30),
        source="approved-demo-source",
    )
    allowed = evaluate_quote(mandate(), quote, {"MXN": snapshot}, now=NOW)
    assert allowed.outcome is PolicyOutcome.ALLOW
    assert allowed.cost is not None
    assert allowed.cost.unbuffered_usd == Decimal("500.00")
    assert allowed.cost.buffered_usd == Decimal("525.00")
    assert allowed.cost.fx_snapshot_ids == ("FX-1",)


def test_stale_fx_fails_closed() -> None:
    quote = proposal(
        components=(CostComponent(name="all-in", amount=Decimal("100"), currency="MXN"),)
    )
    stale = FxSnapshot(
        snapshot_id="FX-old",
        quote_currency="MXN",
        usd_per_unit=Decimal("0.05"),
        observed_at=NOW - timedelta(hours=2, seconds=1),
        source="approved-demo-source",
    )
    assert (
        evaluate_quote(mandate(), quote, {"MXN": stale}, now=NOW).reason
        is ReasonCode.STALE_EVIDENCE
    )


def test_exact_recap_evidence_is_mandatory() -> None:
    quote = proposal(carrier_confirmed_exact_recap=False)
    result = evaluate_quote(mandate(), quote, {}, now=NOW)
    assert (
        require_preagreement_evidence(mandate(), quote, result).reason
        is ReasonCode.EVIDENCE_MISSING
    )


def test_selection_is_lowest_eligible_with_deterministic_tie_break() -> None:
    later = proposal("P-Z", pickup_at=NOW + timedelta(days=2, hours=1))
    earlier = proposal("P-A", pickup_at=NOW + timedelta(days=2))
    decisions = [(q, evaluate_quote(mandate(), q, {}, now=NOW)) for q in (later, earlier)]
    assert select_best(decisions) == earlier

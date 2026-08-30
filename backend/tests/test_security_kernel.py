"""Tests for immutable authorization inputs and deterministic proposal checks."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain import (
    CommitmentMode,
    CostComponent,
    FxSnapshot,
    Mandate,
    QuoteProposal,
    TrustedSessionIdentity,
)
from app.policy.security import evaluate_quote_proposal


def _now() -> datetime:
    return datetime(2026, 8, 29, 12, tzinfo=UTC)


def _mandate(*, fx_margin_bps: int | None = 500) -> Mandate:
    return Mandate(
        mandate_id="MANDATE-OP-1042-V1",
        version=1,
        owner_id="CUSTOMER-123",
        operation_id="OP-1042",
        max_all_in_usd=Decimal("9000"),
        pickup_not_before=datetime(2026, 9, 2, tzinfo=UTC),
        pickup_not_after=datetime(2026, 9, 4, 23, 59, tzinfo=UTC),
        allowed_equipment=frozenset({"40-foot container chassis"}),
        commitment_mode=CommitmentMode.AUTONOMOUS,
        fx_margin_bps=fx_margin_bps,
    )


def _proposal(*, currency: str = "MXN") -> QuoteProposal:
    return QuoteProposal(
        proposal_id="PROPOSAL-1",
        operation_id="OP-1042",
        carrier_id="CARRIER-1",
        carrier_contact_id="CONTACT-1",
        components=(CostComponent(name="Freight", amount=Decimal("1000"), currency=currency),),
        cost_is_final=True,
        pickup_at=datetime(2026, 9, 3, 10, tzinfo=UTC),
        equipment="40-foot container chassis",
        valid_until=_now() + timedelta(hours=1),
        source_call_id="CALL-1",
        source_event_id="EVENT-1",
        transcript_anchor_ms=42_000,
        carrier_confirmed_exact_recap=True,
        confirmed_at=_now(),
    )


def _identity() -> TrustedSessionIdentity:
    return TrustedSessionIdentity(
        trusted_carrier_name="Carrier One",
        trusted_carrier_id="CARRIER-1",
        trusted_contact_id="CONTACT-1",
    )


def test_mandate_is_frozen() -> None:
    mandate = _mandate()

    with pytest.raises(ValidationError):
        mandate.max_all_in_usd = Decimal("10000")  # type: ignore[misc]


def test_non_usd_quote_without_human_margin_fails_closed() -> None:
    decision = evaluate_quote_proposal(
        _mandate(fx_margin_bps=None),
        _proposal(),
        _identity(),
        {"MXN": _snapshot(_now())},
        _now(),
    )

    assert decision.verdict == "deny"
    assert decision.reason_code == "FX_MARGIN_REQUIRED"


def test_future_or_stale_fx_snapshot_is_rejected() -> None:
    future = evaluate_quote_proposal(
        _mandate(),
        _proposal(),
        _identity(),
        {"MXN": _snapshot(_now() + timedelta(minutes=1))},
        _now(),
    )
    stale = evaluate_quote_proposal(
        _mandate(),
        _proposal(),
        _identity(),
        {"MXN": _snapshot(_now() - timedelta(hours=2, seconds=1))},
        _now(),
    )

    assert future.reason_code == "FX_SNAPSHOT_FROM_FUTURE"
    assert stale.reason_code == "FX_SNAPSHOT_STALE"


def test_trusted_session_identity_cannot_be_replaced_by_proposal_claims() -> None:
    proposal = _proposal()
    proposal = proposal.model_copy(update={"carrier_id": "CALLER-CLAIM"})

    decision = evaluate_quote_proposal(
        _mandate(), proposal, _identity(), {"MXN": _snapshot(_now())}, _now()
    )

    assert decision.reason_code == "UNTRUSTED_CARRIER"


def test_fx_margin_applies_only_to_the_foreign_exchange_exposure() -> None:
    mandate = _mandate().model_copy(update={"max_all_in_usd": Decimal("9006")})
    proposal = _proposal().model_copy(
        update={
            "components": (
                CostComponent(name="USD freight", amount=Decimal("9000"), currency="USD"),
                CostComponent(name="MXN tolls", amount=Decimal("100"), currency="MXN"),
            )
        }
    )

    decision = evaluate_quote_proposal(
        mandate, proposal, _identity(), {"MXN": _snapshot(_now())}, _now()
    )

    assert decision.verdict == "allow"
    assert decision.buffered_total_usd == Decimal("9005.6700")


def _snapshot(observed_at: datetime) -> FxSnapshot:
    return FxSnapshot(
        snapshot_id="FX-MXN-1",
        quote_currency="MXN",
        usd_per_unit=Decimal("0.054"),
        observed_at=observed_at,
        source="approved-provider",
    )

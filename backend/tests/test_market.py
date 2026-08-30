"""Three carriers at once, and exactly one award.

Invariant #5 is the one whose failure is worst: two accepted offers means two trucks and
two invoices for one container. These tests are mostly about what the market *refuses*.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain import (
    CommitmentMode,
    CostComponent,
    Mandate,
    PolicyOutcome,
    QuoteProposal,
    ReasonCode,
)
from app.market import MarketError, Rfq, RfqPhase

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def _mandate() -> Mandate:
    return Mandate(
        mandate_id="M-1",
        version=1,
        owner_id="owner",
        operation_id="OP-1",
        max_all_in_usd=Decimal("9000"),
        pickup_not_before=NOW + timedelta(days=1),
        pickup_not_after=NOW + timedelta(days=3),
        allowed_equipment=frozenset({"dry-van"}),
        commitment_mode=CommitmentMode.AUTONOMOUS,
    )


def _offer(carrier: str, amount: str, **changes: object) -> QuoteProposal:
    values: dict[str, object] = {
        "proposal_id": f"P-{carrier}",
        "operation_id": "OP-1",
        "carrier_id": carrier,
        "carrier_contact_id": f"contact-{carrier}",
        "components": (CostComponent(name="all-in", amount=Decimal(amount), currency="USD"),),
        "cost_is_final": True,
        "pickup_at": NOW + timedelta(days=2),
        "equipment": "dry-van",
        "valid_until": NOW + timedelta(hours=1),
        "source_call_id": f"CA-{carrier}",
        "source_event_id": f"EV-{carrier}",
        "transcript_anchor_ms": 4200,
        "carrier_confirmed_exact_recap": True,
        "confirmed_at": NOW,
    }
    values.update(changes)
    return QuoteProposal(**values)  # type: ignore[arg-type]


def _market_of_three() -> Rfq:
    rfq = Rfq(rfq_id="RFQ-1", operation_id="OP-1")
    rfq.record_offer(_offer("pacifico", "8700"))
    rfq.record_offer(_offer("colima", "8500"))
    rfq.record_offer(_offer("manzanillo", "9600"))  # over the 9,000 cap
    return rfq


async def test_three_carriers_are_dialled_at_once_not_one_after_another() -> None:
    """Serial dialling is the thing being replaced; demurrage runs while you wait."""
    rfq = Rfq(rfq_id="RFQ-1", operation_id="OP-1")
    for name in ("pacifico", "colima", "manzanillo"):
        rfq.invite(name, f"+5233000000{len(name)}")
    in_flight = 0
    peak = 0

    async def dial(phone: str) -> str:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return f"CA-{phone[-1]}"

    results = await rfq.dial_all(dial)

    assert peak == 3, "the three calls must overlap, not queue"
    assert all(call_id for call_id in results.values())
    assert all(p.call_id for p in rfq.participants.values())


async def test_a_carrier_that_does_not_answer_does_not_fail_the_rfq() -> None:
    rfq = Rfq(rfq_id="RFQ-1", operation_id="OP-1")
    rfq.invite("pacifico", "+523300000001")
    rfq.invite("colima", "+523300000002")

    async def dial(phone: str) -> str:
        if phone.endswith("2"):
            raise ConnectionError("no answer")
        return "CA-1"

    results = await rfq.dial_all(dial)

    assert results["pacifico"] == "CA-1"
    assert results["colima"] is None
    assert rfq.participants["colima"].call_id is None
    assert rfq.phase is RfqPhase.OPEN


def test_three_carriers_may_hold_offers_at_the_same_time() -> None:
    """The whole point of calling three. Concurrent offers are normal, not a conflict."""
    rfq = _market_of_three()

    assert len(rfq.offers) == 3
    assert rfq.phase is RfqPhase.OPEN


def test_a_carrier_improving_its_own_quote_replaces_only_its_own() -> None:
    rfq = _market_of_three()

    rfq.record_offer(_offer("pacifico", "8400", proposal_id="P-pacifico-2"))

    assert len(rfq.offers) == 3
    amounts = {o.carrier_id: o.components[0].amount for o in rfq.offers}
    assert amounts["pacifico"] == Decimal("8400")
    assert amounts["colima"] == Decimal("8500")


def test_the_comparison_explains_why_each_carrier_did_not_win() -> None:
    """The auditable comparison the brief asks for: not a price list, a set of reasons."""
    rfq = _market_of_three()

    table = rfq.compare(_mandate(), {}, now=NOW)

    by_carrier = {r.proposal.carrier_id: r for r in table}
    assert by_carrier["colima"].rank == 0
    assert by_carrier["pacifico"].rank == 1
    # Over the cap is a different fact from "someone was cheaper", and the table says so.
    assert by_carrier["manzanillo"].rank is None
    assert by_carrier["manzanillo"].decision.outcome is PolicyOutcome.ESCALATE
    assert by_carrier["manzanillo"].decision.reason is ReasonCode.OUTSIDE_MANDATE


def test_award_picks_the_cheapest_eligible_offer() -> None:
    rfq = _market_of_three()
    rfq.begin_awarding()

    award = rfq.award(_mandate(), {}, now=NOW)

    assert award.awarded
    assert award.winner is not None
    assert award.winner.carrier_id == "colima"
    # The comparison ships with the award so the human never has to reconstruct it.
    assert len(award.comparison) == 3


def test_award_cannot_run_before_the_market_is_locked() -> None:
    """RFQ and AWARD are separate phases (invariant #5)."""
    rfq = _market_of_three()

    with pytest.raises(MarketError, match="AWARDING"):
        rfq.award(_mandate(), {}, now=NOW)


def test_a_late_offer_cannot_change_a_decision_already_being_made() -> None:
    rfq = _market_of_three()
    rfq.begin_awarding()

    with pytest.raises(MarketError, match="offers are no longer accepted"):
        rfq.record_offer(_offer("latecomer", "100"))


def test_only_one_award_may_ever_run() -> None:
    """Two open bookings is the worst failure this system can produce."""
    rfq = _market_of_three()
    rfq.begin_awarding()
    rfq.award(_mandate(), {}, now=NOW)

    # Awarding closes the market and nothing reopens it, so the second attempt has no
    # phase to run in. That is the guarantee, not a separate "already awarded" flag.
    assert rfq.phase is RfqPhase.CLOSED
    with pytest.raises(MarketError, match="AWARDING"):
        rfq.award(_mandate(), {}, now=NOW)
    with pytest.raises(MarketError, match="closed"):
        rfq.begin_awarding()


def test_an_rfq_with_nothing_eligible_closes_without_awarding() -> None:
    """Closing anyway is deliberate: an RFQ left open after a failed award gets awarded twice."""
    rfq = Rfq(rfq_id="RFQ-1", operation_id="OP-1")
    rfq.record_offer(_offer("manzanillo", "9600"))
    rfq.begin_awarding()

    award = rfq.award(_mandate(), {}, now=NOW)

    assert not award.awarded
    assert award.winner is None
    assert award.reason is ReasonCode.NO_ELIGIBLE_CANDIDATE
    assert rfq.phase is RfqPhase.CLOSED


def test_an_offer_from_another_operation_is_refused() -> None:
    rfq = _market_of_three()

    with pytest.raises(MarketError, match="different operation"):
        rfq.record_offer(_offer("pacifico", "8000", operation_id="OP-OTHER"))


def test_refusal_ends_rfq_cleanly() -> None:
    """UGLY_CASES row 4. "We don't serve that lane": close politely, carry on with the rest.

    A refusal is an ordinary outcome of asking three carriers. The round continues, the
    refusing carrier stops being a candidate, and why they are out stays on the record.
    """
    rfq = _market_of_three()

    rfq.mark_unavailable("colima", "does not serve Manzanillo to Guadalajara")

    assert "colima" not in {o.carrier_id for o in rfq.offers}
    assert rfq.unavailable["colima"] == "does not serve Manzanillo to Guadalajara"
    assert rfq.phase is RfqPhase.OPEN, "one refusal must not end the round"

    rfq.begin_awarding()
    award = rfq.award(_mandate(), {}, now=NOW)

    # The market carried on and awarded the next best carrier that was actually available.
    assert award.awarded
    assert award.winner is not None
    assert award.winner.carrier_id == "pacifico"


def test_a_carrier_that_refused_cannot_quote_again_in_the_same_round() -> None:
    rfq = _market_of_three()
    rfq.mark_unavailable("colima", "does not serve that lane")

    with pytest.raises(MarketError, match="unavailable"):
        rfq.record_offer(_offer("colima", "8000"))

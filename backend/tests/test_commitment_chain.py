"""The step between a policy verdict and operation state.

Every test here asks the same question in a different way: after this call, what does the
system actually know? The brief's answer is a commitment, written down, anchored to the
second of audio where it was agreed, and only real once the written recap has gone out.
Before this module existed the pipeline stopped at "recap generated" and none of those
rows were ever written.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain import (
    ChainState,
    CommitmentMode,
    CostComponent,
    Mandate,
    OfferRow,
    PolicyOutcome,
    QuoteProposal,
    ReasonCode,
    Recap,
    RecapDelivery,
    RecapDeliveryStatus,
)
from app.repo import InMemoryOperationStore
from app.tools import CommitmentChain

NOW = datetime(2026, 8, 29, 18, 0, tzinfo=UTC)
RFQ = "RFQ-1"
SEGMENT = "SEG-1"


def _mandate(mode: CommitmentMode = CommitmentMode.AUTONOMOUS) -> Mandate:
    return Mandate(
        mandate_id="M-1",
        version=1,
        owner_id="owner",
        operation_id="OP-1",
        max_all_in_usd=Decimal("1000"),
        pickup_not_before=NOW + timedelta(days=1),
        pickup_not_after=NOW + timedelta(days=3),
        allowed_equipment=frozenset({"dry-van"}),
        commitment_mode=mode,
    )


def _proposal(**changes: object) -> QuoteProposal:
    values: dict[str, object] = {
        "proposal_id": "P-1",
        "operation_id": "OP-1",
        "carrier_id": "carrier-a",
        "carrier_contact_id": "verified-contact",
        "components": (CostComponent(name="all-in", amount=Decimal("900"), currency="USD"),),
        "cost_is_final": True,
        "pickup_at": NOW + timedelta(days=2),
        "equipment": "dry-van",
        "valid_until": NOW + timedelta(hours=1),
        "source_call_id": "CA-1",
        "source_event_id": "EV-1",
        "transcript_anchor_ms": 4200,
        "carrier_confirmed_exact_recap": True,
        "confirmed_at": NOW,
    }
    values.update(changes)
    return QuoteProposal(**values)  # type: ignore[arg-type]


def _recap() -> Recap:
    return Recap(call_sid="CA-1", summary="Pickup Thursday 06:00, USD 900, dry van.")


class _Sender:
    """A recap channel whose outcome the test chooses. Never raises, like the real one."""

    def __init__(self, status: RecapDeliveryStatus = RecapDeliveryStatus.SENT) -> None:
        self._status = status
        self.sent_to: list[str] = []

    async def send(self, recap: Recap, to_email: str) -> RecapDelivery:
        self.sent_to.append(to_email)
        return RecapDelivery(
            call_sid=recap.call_sid,
            status=self._status,
            to_email=to_email,
            error=None if self._status is RecapDeliveryStatus.SENT else "550 mailbox unavailable",
        )


def _chain(store: InMemoryOperationStore, sender: _Sender) -> CommitmentChain:
    return CommitmentChain(store, sender, recap_to_email="ops@textilespacifico.mx")


async def _settle(
    store: InMemoryOperationStore,
    sender: _Sender,
    proposal: QuoteProposal | None = None,
    mandate: Mandate | None = None,
):
    return await _chain(store, sender).settle(
        mandate=mandate or _mandate(),
        proposal=proposal or _proposal(),
        fx={},
        recap=_recap(),
        rfq_id=RFQ,
        participant_segment_id=SEGMENT,
        now=NOW,
    )


@pytest.mark.asyncio
async def test_authorized_proposal_reaches_committed_only_after_the_recap_is_out() -> None:
    store, sender = InMemoryOperationStore(), _Sender()

    result = await _settle(store, sender)

    assert result.committed
    assert result.state is ChainState.COMMITTED
    assert sender.sent_to == ["ops@textilespacifico.mx"]
    # The ordering is the claim being made, not an incidental detail: the recap goes out
    # before the commitment counts, and both facts are visible afterwards.
    states = [t["to_state"] for t in await store.list_transitions(result.commitment_id or "")]
    assert states == ["VERBAL", "RECAP_SENT", "COMMITTED"]


@pytest.mark.asyncio
async def test_commitment_is_anchored_to_the_second_it_was_agreed() -> None:
    store, sender = InMemoryOperationStore(), _Sender()

    result = await _settle(store, sender)

    anchors = [e["audio_offset_ms"] for e in store.evidence]
    assert anchors == [4200]
    assert store.evidence[0]["commitment_id"] == result.commitment_id


@pytest.mark.asyncio
async def test_recap_failure_blocks_commitment() -> None:
    """UGLY_CASES row 10. A send failure is terminal, never a partial success."""
    store, sender = InMemoryOperationStore(), _Sender(RecapDeliveryStatus.FAILED)

    result = await _settle(store, sender)

    assert not result.committed
    assert result.state is ChainState.RECAP_FAILED
    assert await store.commitment_state(result.commitment_id or "") is ChainState.RECAP_FAILED
    states = [t["to_state"] for t in await store.list_transitions(result.commitment_id or "")]
    assert "COMMITTED" not in states


@pytest.mark.asyncio
async def test_above_cap_offer_never_commits() -> None:
    """UGLY_CASES rows 1 and 5. The refusal is a row, so it can be shown, not asserted."""
    store, sender = InMemoryOperationStore(), _Sender()
    over = _proposal(
        components=(CostComponent(name="all-in", amount=Decimal("1050"), currency="USD"),)
    )

    result = await _settle(store, sender, over)

    assert result.decision.outcome is PolicyOutcome.ESCALATE
    assert result.decision.reason is ReasonCode.OUTSIDE_MANDATE
    assert result.commitment_id is None
    assert store.commitments == {}
    assert sender.sent_to == []
    # The denial is still written down, with the proposal that caused it.
    assert [d["verdict"] for d in store.decisions.values()] == ["escalate"]


@pytest.mark.asyncio
async def test_missing_offset_is_not_verified() -> None:
    """UGLY_CASES row 11. No anchor means EVIDENCE_MISSING, never a commitment."""
    store, sender = InMemoryOperationStore(), _Sender()

    result = await _settle(store, sender, _proposal(transcript_anchor_ms=None))

    assert result.decision.reason is ReasonCode.EVIDENCE_MISSING
    assert result.commitment_id is None
    assert store.evidence == []


@pytest.mark.asyncio
async def test_a_settled_commitment_cannot_skip_its_evidence() -> None:
    """The store refuses what the Postgres trigger refuses, so tests catch it offline."""
    store = InMemoryOperationStore()
    offer_id = await store.record_offer(
        OfferRow(rfq_id=RFQ, counterparty_id="carrier-a", quoted_currency="USD")
    )
    commitment_id = await store.open_commitment(
        operation_id="OP-1",
        offer_id=offer_id,
        participant_segment_id=SEGMENT,
        audio_offset_ms=1,
    )
    store.evidence.clear()

    with pytest.raises(ValueError, match="no evidence row"):
        await store.transition(commitment_id, to_state=ChainState.COMMITTED, reason="x")


@pytest.mark.asyncio
async def test_single_award_under_race() -> None:
    """UGLY_CASES row 14. Two dispatchers confirm at once; exactly one award survives."""
    store, sender = InMemoryOperationStore(), _Sender()

    first = await _settle(store, sender)
    second = await _settle(
        store,
        sender,
        _proposal(proposal_id="P-2", source_event_id="EV-2", carrier_id="carrier-b"),
    )

    assert first.committed
    accepted = [o for o in store.offers.values() if o["status"] == "accepted"]
    assert len(accepted) == 1
    assert second.state is not ChainState.COMMITTED

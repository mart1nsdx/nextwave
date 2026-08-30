"""The case spine, exercised against the in-memory repository.

The Supabase implementation is not reachable from a test — it needs a network and a
service-role key — so what this file can check about it is that it still satisfies the
same Protocol. That is the seam where the two would drift: a method added to one and not
the other. Behavioural assertions run against the in-memory one, which sim_call uses too.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.domain import (
    AuditEvent,
    AuditEventKind,
    AuditSubjectType,
    CallBinding,
    CallPhase,
    CostComponent,
    Offer,
    OperationRepository,
    RfqPhase,
)
from app.repo import InMemoryOperationRepository, SupabaseOperationRepository
from scripts.seed_demo import DEMO_CARRIERS, DEMO_MANDATE_ROW, DEMO_OPERATION_ID, seed

NOW = datetime(2026, 8, 29, 18, 0, tzinfo=UTC)
CALL_ID = UUID("0197b5f0-0000-4000-8000-0000000000aa")
CALL_SID = "CA-seed-1"


async def _seeded() -> InMemoryOperationRepository:
    repo = InMemoryOperationRepository()
    await seed(repo)
    return repo


def _offer(rfq_id: UUID, *, proposal_id: str, amount: str) -> Offer:
    carrier, contact = DEMO_CARRIERS[0]
    return Offer(
        rfq_id=rfq_id,
        carrier_id=carrier.id,
        carrier_contact_id=contact.id,
        call_id=CALL_ID,
        proposal_id=proposal_id,
        source_event_id=f"EV-{proposal_id}",
        components=(CostComponent(name="all-in", amount=Decimal(amount), currency="USD"),),
        cost_is_final=True,
        pickup_at=datetime(2026, 9, 3, tzinfo=UTC),
        equipment="40-foot container chassis",
        transcript_anchor_ms=4200,
        created_at=NOW,
    )


def _public_async_methods(cls: type) -> set[str]:
    return {
        name
        for name, member in inspect.getmembers(cls, inspect.iscoroutinefunction)
        if not name.startswith("_")
    }


def test_both_implementations_expose_the_same_protocol() -> None:
    """A method added to one repository and not the other is the drift that makes a
    green test suite say nothing about production."""
    assert issubclass(InMemoryOperationRepository, OperationRepository)
    assert issubclass(SupabaseOperationRepository, OperationRepository)

    in_memory = _public_async_methods(InMemoryOperationRepository)
    supabase = _public_async_methods(SupabaseOperationRepository)
    assert in_memory == supabase, f"only in one: {in_memory ^ supabase}"

    declared = _public_async_methods(OperationRepository)
    assert declared <= in_memory, f"Protocol methods missing: {sorted(declared - in_memory)}"

    for name in sorted(declared):
        expected = inspect.signature(getattr(OperationRepository, name))
        for impl in (InMemoryOperationRepository, SupabaseOperationRepository):
            assert inspect.signature(getattr(impl, name)) == expected, (
                f"{impl.__name__}.{name} does not match the Protocol signature"
            )


async def test_seed_is_idempotent_and_readable() -> None:
    repo = await _seeded()
    await seed(repo)  # second run must not duplicate or rewrite anything

    operation = await repo.get_operation(str(DEMO_OPERATION_ID))
    assert operation is not None
    assert (operation.origin, operation.destination) == ("Manzanillo", "Guadalajara")

    mandate = await repo.current_mandate(str(DEMO_OPERATION_ID))
    assert mandate is not None
    assert mandate.max_all_in_usd == Decimal("9000")
    assert mandate.pickup_not_before == datetime(2026, 9, 2, tzinfo=UTC)
    assert mandate.version == 1

    assert len(DEMO_CARRIERS) == 3


async def test_current_mandate_is_the_highest_version() -> None:
    """A mandate change is a new version row, never an UPDATE (invariant #2)."""
    repo = await _seeded()

    # Re-saving version 1 with a different cap must not move the ceiling. The mandate is
    # immutable; this is the write that would quietly raise it if it were not.
    await repo.save_mandate(DEMO_MANDATE_ROW.model_copy(update={"max_all_in_usd": Decimal("1")}))
    unchanged = await repo.current_mandate(str(DEMO_OPERATION_ID))
    assert unchanged is not None
    assert unchanged.max_all_in_usd == Decimal("9000")

    # A real change arrives as version 2.
    await repo.save_mandate(
        DEMO_MANDATE_ROW.model_copy(update={"version": 2, "max_all_in_usd": Decimal("9500")})
    )
    current = await repo.current_mandate(str(DEMO_OPERATION_ID))
    assert current is not None
    assert (current.version, current.max_all_in_usd) == (2, Decimal("9500"))


async def test_claim_awarding_succeeds_once() -> None:
    """Ugly case 14. Two carriers accepting must still produce exactly one award, so the
    right to award is claimed, not assumed."""
    repo = await _seeded()
    rfq = await repo.create_rfq(str(DEMO_OPERATION_ID), str(DEMO_MANDATE_ROW.mandate_id))
    assert rfq.phase is RfqPhase.SOLICITING

    assert await repo.claim_awarding(str(rfq.id)) is True
    assert await repo.claim_awarding(str(rfq.id)) is False
    assert await repo.claim_awarding(str(rfq.id)) is False

    claimed = await repo.get_rfq(str(rfq.id))
    assert claimed is not None
    assert claimed.phase is RfqPhase.AWARDING


async def test_claim_awarding_on_unknown_rfq_is_false() -> None:
    """Fail closed: an RFQ we cannot see is never one we may award (invariant #6)."""
    repo = await _seeded()
    assert await repo.claim_awarding(str(uuid4())) is False


async def test_only_one_live_rfq_per_operation() -> None:
    repo = await _seeded()
    await repo.create_rfq(str(DEMO_OPERATION_ID), str(DEMO_MANDATE_ROW.mandate_id))
    with pytest.raises(ValueError, match="already has a live RFQ"):
        await repo.create_rfq(str(DEMO_OPERATION_ID), str(DEMO_MANDATE_ROW.mandate_id))


async def test_bind_and_resolve_a_call() -> None:
    repo = await _seeded()
    operation = await repo.get_operation(str(DEMO_OPERATION_ID))
    mandate = await repo.current_mandate(str(DEMO_OPERATION_ID))
    assert operation is not None and mandate is not None
    carrier, contact = DEMO_CARRIERS[0]

    binding = CallBinding(
        call_id=CALL_ID,
        call_sid=CALL_SID,
        operation=operation,
        mandate=mandate,
        phase=CallPhase.RFQ,
        carrier=carrier,
        carrier_contact=contact,
    )
    await repo.bind_call(CALL_SID, binding)

    assert await repo.resolve_call(CALL_SID) == binding
    assert await repo.resolve_call("CA-never-seen") is None

    by_number = await repo.resolve_by_caller_number(contact.phone_e164)
    assert [b.call_sid for b in by_number] == [CALL_SID]
    # An unknown number resolves to nothing. That is an escalation, not a guess.
    assert await repo.resolve_by_caller_number("+520000000000") == []


async def test_audit_events_are_idempotent_on_event_key() -> None:
    """Twilio and OpenAI redeliver. A second delivery is a no-op (invariant #7)."""
    repo = await _seeded()
    event = AuditEvent(
        event_key="CA-seed-1:policy:1",
        subject_type=AuditSubjectType.CALL,
        subject_id=CALL_SID,
        kind=AuditEventKind.POLICY_DECISION,
        call_id=CALL_ID,
        reason_code="outside_mandate",
        audio_offset_ms=4200,
    )
    await repo.record_audit_event(event)
    await repo.record_audit_event(event.model_copy(update={"reason_code": "allowed"}))

    stored = await repo.audit_events_for(AuditSubjectType.CALL.value, CALL_SID)
    assert len(stored) == 1
    # First write wins: a replay cannot rewrite the recorded reason.
    assert stored[0].reason_code == "outside_mandate"


async def test_offers_for_rfq_returns_every_offer_heard() -> None:
    repo = await _seeded()
    rfq = await repo.create_rfq(str(DEMO_OPERATION_ID), str(DEMO_MANDATE_ROW.mandate_id))
    await repo.save_offer(_offer(rfq.id, proposal_id="P-1", amount="8500"))
    await repo.save_offer(_offer(rfq.id, proposal_id="P-2", amount="8200"))

    offers = await repo.offers_for_rfq(str(rfq.id))
    assert {o.proposal_id for o in offers} == {"P-1", "P-2"}
    assert await repo.offers_for_rfq(str(uuid4())) == []


async def test_redelivered_offer_does_not_overwrite() -> None:
    """Same proposal_id twice is a redelivery, and a redelivery changes nothing."""
    repo = await _seeded()
    rfq = await repo.create_rfq(str(DEMO_OPERATION_ID), str(DEMO_MANDATE_ROW.mandate_id))
    await repo.save_offer(_offer(rfq.id, proposal_id="P-1", amount="8500"))
    await repo.save_offer(_offer(rfq.id, proposal_id="P-1", amount="99"))

    offers = await repo.offers_for_rfq(str(rfq.id))
    assert len(offers) == 1
    assert offers[0].components[0].amount == Decimal("8500")

"""Interfaces the outer layers depend on without importing the inner ones.

``telephony/`` and ``realtime/`` need to persist evidence, but the layering contract
(tests/test_layering.py) forbids them from importing ``repo/`` or ``ledger/``. They take
a ``TranscriptStore`` instead, wired in from the composition root. Same idea for the
model seam: ``agent/`` depends on ``RecapModel``, not on a vendor SDK.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.models import (
    AuditEvent,
    CallBinding,
    CallBrief,
    CallCase,
    CallDirection,
    Carrier,
    CarrierContact,
    HandoffEvent,
    HandoffRequest,
    Offer,
    Operation,
    Recap,
    RecapContext,
    RecapDelivery,
    Rfq,
    TranscriptEvent,
)
from app.domain.security import Mandate


class TranscriptStore(Protocol):
    """Persistence for call evidence. Every method is idempotent on its natural key."""

    async def open_case(
        self,
        call_sid: str,
        direction: CallDirection,
        *,
        from_number: str | None = None,
        to_number: str | None = None,
    ) -> None: ...

    async def close_case(self, call_sid: str, *, failed: bool = False) -> None: ...

    async def record_event(self, event: TranscriptEvent) -> None:
        """Append one transcript event. A second call with the same event_key is a no-op."""

    async def list_events(self, call_sid: str) -> list[TranscriptEvent]:
        """All events for a call, ordered by audio offset then sequence."""

    async def get_case(self, call_sid: str) -> CallCase | None: ...

    async def list_cases(self, *, limit: int = 50) -> list[CallCase]: ...

    async def save_recap(self, recap: Recap) -> None: ...

    async def get_recap(self, call_sid: str) -> Recap | None: ...

    async def save_brief(self, brief: CallBrief) -> None: ...

    async def get_brief(self, call_sid: str) -> CallBrief | None: ...

    async def set_recap_delivery(self, delivery: RecapDelivery) -> None: ...

    async def get_recap_delivery(self, call_sid: str) -> RecapDelivery | None: ...

    async def create_handoff(self, request: HandoffRequest) -> bool:
        """Store a request once. False means this call already has a handoff."""

    async def get_handoff(self, handoff_id: str) -> HandoffRequest | None: ...

    async def get_handoff_for_call(self, call_sid: str) -> HandoffRequest | None: ...

    async def record_handoff_event(self, event: HandoffEvent) -> None:
        """Append an idempotent lifecycle event and advance its visible status."""

    async def list_handoff_events(self, handoff_id: str) -> list[HandoffEvent]: ...

    async def update_handoff_transport(
        self,
        handoff_id: str,
        *,
        conference_name: str | None = None,
        operator_call_sid: str | None = None,
    ) -> None: ...


@runtime_checkable
class OperationRepository(Protocol):
    """Persistence for the business case: operation, mandate, RFQ, offers, audit trail.

    Two implementations exist and must behave identically — an in-memory one for tests
    and ``sim_call``, and a Supabase one. That equivalence is what makes the test suite
    mean anything about production. ``runtime_checkable`` so the suite can assert both
    still satisfy it.

    Nothing here decides. The repository obeys; ``policy/`` decides.
    """

    # --- setup writes: how a case comes into existence at all ---
    async def save_operation(self, operation: Operation) -> None: ...

    async def save_mandate(self, mandate: Mandate) -> None:
        """Store one immutable mandate version. A version already on file is never
        rewritten; a change is a new version row (AGENTS.md invariant #2)."""

    async def save_carrier(self, carrier: Carrier) -> None: ...

    async def save_carrier_contact(self, contact: CarrierContact) -> None: ...

    # --- the case ---
    async def get_operation(self, operation_id: str) -> Operation | None: ...

    async def current_mandate(self, operation_id: str) -> Mandate | None:
        """The highest-version mandate for the operation.

        Mandates are immutable rows: a change is version+1, never an UPDATE, so "current"
        is a read and never a race (AGENTS.md invariant #2).
        """

    async def create_rfq(self, operation_id: str, mandate_id: str) -> Rfq:
        """Open a soliciting round. Raises ValueError if one is already live for the
        operation — invariant #5 allows exactly one."""

    async def get_rfq(self, rfq_id: str) -> Rfq | None: ...

    async def claim_awarding(self, rfq_id: str) -> bool:
        """UPDATE rfqs SET phase='awarding' WHERE id=? AND phase='soliciting'.
        False means another awarder won the race."""

    async def bind_call(self, call_sid: str, binding: CallBinding) -> None:
        """Attach a call to its case. Resolved once, before the session is built."""

    async def resolve_call(self, call_sid: str) -> CallBinding | None:
        """The binding for a call, or None if it was never bound."""

    async def resolve_by_caller_number(self, phone_e164: str) -> list[CallBinding]:
        """Bindings of calls already bound to the carrier reachable at this number.

        Empty is the normal answer for a stranger. It is not a licence to guess: an
        unresolvable inbound call escalates and produces no offer (invariant #6).
        """

    async def save_offer(self, offer: Offer) -> None:
        """Append one offer. First write wins on ``proposal_id``.

        A later utterance never edits an earlier offer; it arrives here as a second row
        with its own proposal_id and timestamp (invariant #4). A redelivered proposal_id
        is a no-op (invariant #7).
        """

    async def offers_for_rfq(self, rfq_id: str) -> list[Offer]:
        """Every offer heard in this round, oldest first. Nothing is collapsed."""

    async def record_audit_event(self, event: AuditEvent) -> None:
        """Append-only, idempotent on event_key. The single writer for audit_events."""

    async def audit_events_for(self, subject_type: str, subject_id: str) -> list[AuditEvent]:
        """What the system did about one subject, oldest first."""


class RecapModel(Protocol):
    """The LLM seam. Given a transcript, return structured content — no side effects."""

    async def summarize(self, transcript: str, context: RecapContext) -> Recap: ...

    async def brief(self, transcript: str) -> CallBrief: ...


class RecapSender(Protocol):
    """Delivers the recap by email. Returns the outcome; never raises for a send failure."""

    async def send(self, recap: Recap, to_email: str) -> RecapDelivery: ...


class TranscriptSink(Protocol):
    """What ``realtime/`` calls when a transcript segment is ready. Wired to the ledger."""

    async def __call__(self, event: TranscriptEvent) -> None: ...


class CallCompletedHook(Protocol):
    """What ``telephony/`` calls when Twilio reports a call finished. Wired to RecapService."""

    async def __call__(self, call_sid: str) -> None: ...

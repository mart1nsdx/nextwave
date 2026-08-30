"""OperationRepository implementations — the business case behind a phone call.

Two implementations, one Protocol (``domain/ports.py``). The in-memory one is what
``sim_call`` and the test suite run against; the Supabase one is what production uses.
Their behaviour must match, method for method, including what they refuse: that
equivalence is the only reason a green test suite says anything about the live path.

The Supabase client is synchronous; its calls run in a worker thread so they never block
the event loop that is also pumping a live Media Stream. All database access in the
codebase goes through repo/ (AGENTS.md) — a Supabase client built anywhere else is a bug.

Nothing in this module decides anything. It stores what it is given and refuses what the
schema refuses. Authorization is policy/'s job.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.config import Settings
from app.domain.models import (
    AuditEvent,
    CallBinding,
    CallPhase,
    Carrier,
    CarrierContact,
    Offer,
    Operation,
    Rfq,
    RfqPhase,
)
from app.domain.security import CommitmentMode, Mandate

_LIVE_PHASES = (RfqPhase.SOLICITING, RfqPhase.AWARDING)

# Raised as ValueError by both implementations so a caller can handle one failure mode.
_RFQ_ALREADY_LIVE = "operation {0} already has a live RFQ"


def _now() -> datetime:
    return datetime.now(UTC)


class InMemoryOperationRepository:
    """No network. Used by sim_call and the test suite; behaviour must match Supabase."""

    def __init__(self) -> None:
        self._operations: dict[str, Operation] = {}
        self._mandates: dict[str, list[Mandate]] = {}
        self._carriers: dict[str, Carrier] = {}
        self._contacts: dict[str, CarrierContact] = {}
        self._rfqs: dict[str, Rfq] = {}
        self._bindings: dict[str, CallBinding] = {}
        self._offers: dict[str, Offer] = {}
        self._audit: dict[str, AuditEvent] = {}

    # --- setup writes ---------------------------------------------------------------

    async def save_operation(self, operation: Operation) -> None:
        self._operations[str(operation.id)] = operation

    async def save_mandate(self, mandate: Mandate) -> None:
        versions = self._mandates.setdefault(mandate.operation_id, [])
        # Immutable: a version already on file is never rewritten (invariant #2).
        if any(m.version == mandate.version for m in versions):
            return
        versions.append(mandate)

    async def save_carrier(self, carrier: Carrier) -> None:
        self._carriers[str(carrier.id)] = carrier

    async def save_carrier_contact(self, contact: CarrierContact) -> None:
        self._contacts[str(contact.id)] = contact

    # --- reads ----------------------------------------------------------------------

    async def get_operation(self, operation_id: str) -> Operation | None:
        return self._operations.get(operation_id)

    async def current_mandate(self, operation_id: str) -> Mandate | None:
        versions = self._mandates.get(operation_id)
        if not versions:
            return None
        return max(versions, key=lambda m: m.version)

    async def get_rfq(self, rfq_id: str) -> Rfq | None:
        return self._rfqs.get(rfq_id)

    # --- RFQ lifecycle --------------------------------------------------------------

    async def create_rfq(self, operation_id: str, mandate_id: str) -> Rfq:
        for existing in self._rfqs.values():
            if str(existing.operation_id) == operation_id and existing.phase in _LIVE_PHASES:
                raise ValueError(_RFQ_ALREADY_LIVE.format(operation_id))
        rfq = Rfq(
            operation_id=UUID(operation_id),
            mandate_id=UUID(mandate_id),
            phase=RfqPhase.SOLICITING,
            created_at=_now(),
        )
        self._rfqs[str(rfq.id)] = rfq
        return rfq

    async def claim_awarding(self, rfq_id: str) -> bool:
        rfq = self._rfqs.get(rfq_id)
        if rfq is None or rfq.phase is not RfqPhase.SOLICITING:
            return False
        self._rfqs[rfq_id] = rfq.model_copy(update={"phase": RfqPhase.AWARDING})
        return True

    # --- call binding ---------------------------------------------------------------

    async def bind_call(self, call_sid: str, binding: CallBinding) -> None:
        self._bindings.pop(call_sid, None)  # re-insert so ordering is newest-bound-last
        self._bindings[call_sid] = binding

    async def resolve_call(self, call_sid: str) -> CallBinding | None:
        return self._bindings.get(call_sid)

    async def resolve_by_caller_number(self, phone_e164: str) -> list[CallBinding]:
        contact = next(
            (c for c in self._contacts.values() if c.phone_e164 == phone_e164),
            None,
        )
        if contact is None:
            return []
        matches = [
            b
            for b in self._bindings.values()
            if b.carrier is not None and b.carrier.id == contact.carrier_id
        ]
        matches.reverse()  # newest binding first
        return matches

    # --- offers and audit -----------------------------------------------------------

    async def save_offer(self, offer: Offer) -> None:
        # First write wins. A different price is a different proposal_id and therefore a
        # second row; a redelivered one is a no-op (invariants #4 and #7).
        self._offers.setdefault(offer.proposal_id, offer)

    async def offers_for_rfq(self, rfq_id: str) -> list[Offer]:
        return [o for o in self._offers.values() if str(o.rfq_id) == rfq_id]

    async def record_audit_event(self, event: AuditEvent) -> None:
        self._audit.setdefault(event.event_key, event)

    async def audit_events_for(self, subject_type: str, subject_id: str) -> list[AuditEvent]:
        return [
            e
            for e in self._audit.values()
            if e.subject_type.value == subject_type and e.subject_id == subject_id
        ]


class SupabaseOperationRepository:
    """Backed by the case-spine migrations under supabase/migrations/."""

    def __init__(self, settings: Settings) -> None:
        if not settings.supabase_url or not settings.supabase_secret_key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SECRET_KEY must be set")
        # Imported here so the package has no import-time dependency on the SDK — tests
        # that only touch the in-memory repository stay fast and offline.
        from supabase import create_client

        self._db = create_client(settings.supabase_url, settings.supabase_secret_key)

    async def _run(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        return await asyncio.to_thread(fn, *args, **kwargs)

    # --- setup writes ---------------------------------------------------------------

    async def save_operation(self, operation: Operation) -> None:
        row = operation.model_dump(mode="json", exclude_none=True)

        def _upsert() -> Any:
            return self._db.table("operations").upsert(row, on_conflict="id").execute()

        await self._run(_upsert)

    async def save_mandate(self, mandate: Mandate) -> None:
        row: dict[str, Any] = {
            "id": mandate.mandate_id,
            "operation_id": mandate.operation_id,
            "version": mandate.version,
            "owner_id": mandate.owner_id,
            "max_all_in_usd": str(mandate.max_all_in_usd),
            "pickup_not_before": mandate.pickup_not_before.isoformat(),
            "pickup_not_after": mandate.pickup_not_after.isoformat(),
            "allowed_equipment": sorted(mandate.allowed_equipment),
            "commitment_mode": mandate.commitment_mode.value,
            "fx_margin_bps": mandate.fx_margin_bps,
        }

        def _insert() -> Any:
            # ignore_duplicates: a mandate version already on file is never rewritten.
            return (
                self._db.table("mandates")
                .upsert(row, on_conflict="operation_id,version", ignore_duplicates=True)
                .execute()
            )

        await self._run(_insert)

    async def save_carrier(self, carrier: Carrier) -> None:
        row = carrier.model_dump(mode="json", exclude_none=True)

        def _upsert() -> Any:
            return self._db.table("carriers").upsert(row, on_conflict="id").execute()

        await self._run(_upsert)

    async def save_carrier_contact(self, contact: CarrierContact) -> None:
        row = contact.model_dump(mode="json", exclude_none=True)

        def _upsert() -> Any:
            return self._db.table("carrier_contacts").upsert(row, on_conflict="id").execute()

        await self._run(_upsert)

    # --- reads ----------------------------------------------------------------------

    async def get_operation(self, operation_id: str) -> Operation | None:
        def _query() -> Any:
            return (
                self._db.table("operations").select("*").eq("id", operation_id).limit(1).execute()
            )

        rows = (await self._run(_query)).data or []
        return _operation_from_row(rows[0]) if rows else None

    async def current_mandate(self, operation_id: str) -> Mandate | None:
        def _query() -> Any:
            return (
                self._db.table("mandates")
                .select("*")
                .eq("operation_id", operation_id)
                .order("version", desc=True)
                .limit(1)
                .execute()
            )

        rows = (await self._run(_query)).data or []
        return _mandate_from_row(rows[0]) if rows else None

    async def get_rfq(self, rfq_id: str) -> Rfq | None:
        def _query() -> Any:
            return self._db.table("rfqs").select("*").eq("id", rfq_id).limit(1).execute()

        rows = (await self._run(_query)).data or []
        return _rfq_from_row(rows[0]) if rows else None

    # --- RFQ lifecycle --------------------------------------------------------------

    async def create_rfq(self, operation_id: str, mandate_id: str) -> Rfq:
        row = {"operation_id": operation_id, "mandate_id": mandate_id, "phase": "soliciting"}

        def _insert() -> Any:
            return self._db.table("rfqs").insert(row).execute()

        try:
            result = await self._run(_insert)
        except Exception as exc:
            # rfqs_one_live_per_operation is a partial unique index: the database, not a
            # code path, is what stops a second live round (invariant #5).
            if "rfqs_one_live_per_operation" in str(exc):
                raise ValueError(_RFQ_ALREADY_LIVE.format(operation_id)) from exc
            raise
        return _rfq_from_row((result.data or [row])[0])

    async def claim_awarding(self, rfq_id: str) -> bool:
        # One conditional UPDATE, never read-then-write: the WHERE clause is the lock.
        def _update() -> Any:
            return (
                self._db.table("rfqs")
                .update({"phase": RfqPhase.AWARDING.value})
                .eq("id", rfq_id)
                .eq("phase", RfqPhase.SOLICITING.value)
                .execute()
            )

        result = await self._run(_update)
        return bool(result.data)

    # --- call binding ---------------------------------------------------------------

    async def bind_call(self, call_sid: str, binding: CallBinding) -> None:
        patch = {
            "operation_id": str(binding.operation.id),
            "mandate_id": binding.mandate.mandate_id,
            "carrier_id": str(binding.carrier.id) if binding.carrier else None,
            "carrier_contact_id": (
                str(binding.carrier_contact.id) if binding.carrier_contact else None
            ),
            "phase": binding.phase.value,
        }

        def _update() -> Any:
            return self._db.table("calls").update(patch).eq("twilio_call_sid", call_sid).execute()

        await self._run(_update)

    async def resolve_call(self, call_sid: str) -> CallBinding | None:
        def _query() -> Any:
            return (
                self._db.table("calls")
                .select("*")
                .eq("twilio_call_sid", call_sid)
                .limit(1)
                .execute()
            )

        rows = (await self._run(_query)).data or []
        if not rows:
            return None
        return await self._binding_from_call_row(rows[0])

    async def resolve_by_caller_number(self, phone_e164: str) -> list[CallBinding]:
        contact = await self._contact_by_phone(phone_e164)
        if contact is None:
            return []

        def _query() -> Any:
            return (
                self._db.table("calls")
                .select("*")
                .eq("carrier_id", str(contact.carrier_id))
                .not_.is_("operation_id", "null")
                .order("started_at", desc=True)
                .execute()
            )

        rows = (await self._run(_query)).data or []
        bindings = [await self._binding_from_call_row(row) for row in rows]
        return [b for b in bindings if b is not None]

    # --- offers and audit -----------------------------------------------------------

    async def save_offer(self, offer: Offer) -> None:
        row = offer.model_dump(mode="json", exclude_none=True)

        def _upsert() -> Any:
            # ignore_duplicates: a redelivered proposal_id must not rewrite what was
            # heard the first time (invariants #4 and #7).
            return (
                self._db.table("offers")
                .upsert(row, on_conflict="proposal_id", ignore_duplicates=True)
                .execute()
            )

        await self._run(_upsert)

    async def offers_for_rfq(self, rfq_id: str) -> list[Offer]:
        def _query() -> Any:
            return (
                self._db.table("offers")
                .select("*")
                .eq("rfq_id", rfq_id)
                .order("created_at")
                .execute()
            )

        rows = (await self._run(_query)).data or []
        return [_offer_from_row(row) for row in rows]

    async def record_audit_event(self, event: AuditEvent) -> None:
        row = event.model_dump(mode="json", exclude_none=True)

        def _insert() -> Any:
            return (
                self._db.table("audit_events")
                .upsert(row, on_conflict="event_key", ignore_duplicates=True)
                .execute()
            )

        await self._run(_insert)

    async def audit_events_for(self, subject_type: str, subject_id: str) -> list[AuditEvent]:
        def _query() -> Any:
            return (
                self._db.table("audit_events")
                .select("*")
                .eq("subject_type", subject_type)
                .eq("subject_id", subject_id)
                .order("created_at")
                .execute()
            )

        rows = (await self._run(_query)).data or []
        return [AuditEvent.model_validate(row) for row in rows]

    # --- internals ------------------------------------------------------------------

    async def _contact_by_phone(self, phone_e164: str) -> CarrierContact | None:
        def _query() -> Any:
            return (
                self._db.table("carrier_contacts")
                .select("*")
                .eq("phone_e164", phone_e164)
                .limit(1)
                .execute()
            )

        rows = (await self._run(_query)).data or []
        return _contact_from_row(rows[0]) if rows else None

    async def _by_id(self, table: str, row_id: str) -> dict[str, Any] | None:
        def _query() -> Any:
            return self._db.table(table).select("*").eq("id", row_id).limit(1).execute()

        rows = (await self._run(_query)).data or []
        return rows[0] if rows else None

    async def _binding_from_call_row(self, row: dict[str, Any]) -> CallBinding | None:
        """An unbound call is not a partially bound one. Missing case, missing mandate or
        missing phase all mean the same thing: this call is not resolved."""
        operation_id = row.get("operation_id")
        mandate_id = row.get("mandate_id")
        phase = row.get("phase")
        if not operation_id or not mandate_id or not phase:
            return None

        operation_row = await self._by_id("operations", operation_id)
        mandate_row = await self._by_id("mandates", mandate_id)
        if operation_row is None or mandate_row is None:
            return None

        carrier = None
        if row.get("carrier_id"):
            carrier_row = await self._by_id("carriers", row["carrier_id"])
            carrier = _carrier_from_row(carrier_row) if carrier_row else None

        contact = None
        if row.get("carrier_contact_id"):
            contact_row = await self._by_id("carrier_contacts", row["carrier_contact_id"])
            contact = _contact_from_row(contact_row) if contact_row else None

        return CallBinding(
            call_id=UUID(row["id"]),
            call_sid=row["twilio_call_sid"],
            operation=_operation_from_row(operation_row),
            mandate=_mandate_from_row(mandate_row),
            phase=CallPhase(phase),
            carrier=carrier,
            carrier_contact=contact,
        )


def _operation_from_row(row: dict[str, Any]) -> Operation:
    return Operation.model_validate(row)


def _mandate_from_row(row: dict[str, Any]) -> Mandate:
    return Mandate(
        mandate_id=str(row["id"]),
        version=row["version"],
        owner_id=row["owner_id"],
        operation_id=str(row["operation_id"]),
        max_all_in_usd=row["max_all_in_usd"],
        pickup_not_before=row["pickup_not_before"],
        pickup_not_after=row["pickup_not_after"],
        allowed_equipment=frozenset(row["allowed_equipment"]),
        commitment_mode=CommitmentMode(row["commitment_mode"]),
        fx_margin_bps=row.get("fx_margin_bps"),
    )


def _carrier_from_row(row: dict[str, Any]) -> Carrier:
    return Carrier.model_validate(row)


def _contact_from_row(row: dict[str, Any]) -> CarrierContact:
    return CarrierContact.model_validate(row)


def _rfq_from_row(row: dict[str, Any]) -> Rfq:
    return Rfq.model_validate(row)


def _offer_from_row(row: dict[str, Any]) -> Offer:
    return Offer.model_validate(row)

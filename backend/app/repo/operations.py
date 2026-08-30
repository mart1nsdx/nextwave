"""Persistence for the commitment chain: offers, decisions, commitments, evidence.

``store.py`` owns the call-evidence tables; this module owns the operation-state tables.
Same rule as everywhere else — a Supabase client built outside ``repo/`` is a bug.

Nothing here decides anything. It is handed a verdict that ``policy/`` already reached and
writes it down. The database independently refuses some of these writes (one accepted offer
per RFQ, no COMMITTED without an evidence row), and that refusal is the point: the
guarantee survives a mistake in this file.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

from app.config import Settings
from app.domain.commitment import SETTLED_STATES, ChainState, DecisionRow, OfferRow


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class InMemoryOperationStore:
    """No network. Behaviour must match Supabase, including what it refuses."""

    def __init__(self) -> None:
        self.offers: dict[str, dict[str, Any]] = {}
        self.decisions: dict[str, dict[str, Any]] = {}
        self.commitments: dict[str, dict[str, Any]] = {}
        self.transitions: list[dict[str, Any]] = []
        self.evidence: list[dict[str, Any]] = []

    async def record_offer(self, offer: OfferRow) -> str:
        offer_id = str(uuid.uuid4())
        self.offers[offer_id] = offer.model_dump() | {"id": offer_id, "status": "proposed"}
        return offer_id

    async def record_decision(self, decision: DecisionRow) -> str:
        decision_id = str(uuid.uuid4())
        self.decisions[decision_id] = decision.model_dump() | {"id": decision_id}
        return decision_id

    async def accept_offer(self, offer_id: str) -> None:
        rfq = self.offers[offer_id]["rfq_id"]
        # Mirrors offers_one_accepted_per_rfq_idx. Invariant #5: two open bookings is the
        # worst outcome this system can produce, so a second acceptance must fail here
        # exactly as it fails in Postgres.
        for other_id, other in self.offers.items():
            if other_id != offer_id and other["rfq_id"] == rfq and other["status"] == "accepted":
                raise ValueError("an offer is already accepted for this RFQ")
        self.offers[offer_id]["status"] = "accepted"

    async def open_commitment(
        self,
        *,
        operation_id: str,
        offer_id: str,
        participant_segment_id: str,
        audio_offset_ms: int,
        decision_id: str | None = None,
    ) -> str:
        commitment_id = str(uuid.uuid4())
        self.commitments[commitment_id] = {
            "id": commitment_id,
            "operation_id": operation_id,
            "offer_id": offer_id,
            "participant_segment_id": participant_segment_id,
            "chain_state": ChainState.VERBAL.value,
        }
        # Evidence before the transition, always: the database trigger rejects the other
        # order, and a commitment with no anchor is EVIDENCE_MISSING, never verified.
        self.evidence.append({"commitment_id": commitment_id, "audio_offset_ms": audio_offset_ms})
        self.transitions.append(
            {
                "commitment_id": commitment_id,
                "from_state": None,
                "to_state": ChainState.VERBAL.value,
                "reason": "counterparty_confirmed_on_call",
                "policy_decision_id": decision_id,
            }
        )
        return commitment_id

    async def transition(
        self,
        commitment_id: str,
        *,
        to_state: ChainState,
        reason: str,
        decision_id: str | None = None,
    ) -> None:
        commitment = self.commitments[commitment_id]
        has_evidence = any(e["commitment_id"] == commitment_id for e in self.evidence)
        if to_state in SETTLED_STATES and not has_evidence:
            raise ValueError(
                f"commitment {commitment_id} cannot reach {to_state} with no evidence row"
            )
        self.transitions.append(
            {
                "commitment_id": commitment_id,
                "from_state": commitment["chain_state"],
                "to_state": to_state.value,
                "reason": reason,
                "policy_decision_id": decision_id,
            }
        )
        commitment["chain_state"] = to_state.value

    async def commitment_state(self, commitment_id: str) -> ChainState | None:
        row = self.commitments.get(commitment_id)
        return ChainState(row["chain_state"]) if row else None

    async def list_transitions(self, commitment_id: str) -> list[dict[str, Any]]:
        return [t for t in self.transitions if t["commitment_id"] == commitment_id]


class SupabaseOperationStore:
    """Backed by supabase/migrations/20260829165921_policy_and_evidence_spine.sql."""

    def __init__(self, settings: Settings, tenant_id: str) -> None:
        if not settings.supabase_url or not settings.supabase_secret_key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SECRET_KEY must be set")
        # Imported here so the package has no import-time dependency on the SDK, exactly
        # as store.py does — offline tests must stay offline and fast.
        from supabase import create_client

        self._db = create_client(settings.supabase_url, settings.supabase_secret_key)
        self._tenant_id = tenant_id

    async def _run(self, fn: Any) -> Any:
        return await asyncio.to_thread(fn)

    async def _case_id(self, call_sid: str | None) -> str | None:
        if not call_sid:
            return None

        def _query() -> Any:
            return (
                self._db.table("call_cases")
                .select("id")
                .eq("twilio_call_sid", call_sid)
                .limit(1)
                .execute()
            )

        rows = (await self._run(_query)).data or []
        return str(rows[0]["id"]) if rows else None

    async def record_offer(self, offer: OfferRow) -> str:
        row: dict[str, Any] = {
            "tenant_id": self._tenant_id,
            "rfq_id": offer.rfq_id,
            "counterparty_id": offer.counterparty_id,
            "case_id": await self._case_id(offer.call_sid),
            "quoted_currency": offer.quoted_currency,
            "is_total_final": offer.is_total_final,
            "evidence_offset_ms": offer.evidence_offset_ms,
            "policy_amount_usd_minor": offer.policy_amount_usd_minor,
            "fx_snapshot_id": offer.fx_snapshot_id,
            "mandate_id": offer.mandate_id,
            "pickup_window_start": _iso(offer.pickup_window_start),
            "pickup_window_end": _iso(offer.pickup_window_end),
        }

        def _insert() -> Any:
            return self._db.table("offers").insert(row).execute()

        return str((await self._run(_insert)).data[0]["id"])

    async def record_decision(self, decision: DecisionRow) -> str:
        row: dict[str, Any] = {
            "tenant_id": self._tenant_id,
            "operation_id": decision.operation_id,
            "case_id": await self._case_id(decision.call_sid),
            "mandate_id": decision.mandate_id,
            "mandate_version": decision.mandate_version,
            "fx_snapshot_id": decision.fx_snapshot_id,
            "proposal": decision.proposal,
            "verdict": decision.verdict,
            "reason_code": decision.reason_code,
            "rule_fired": decision.rule_fired,
        }

        def _insert() -> Any:
            return self._db.table("policy_decisions").insert(row).execute()

        return str((await self._run(_insert)).data[0]["id"])

    async def accept_offer(self, offer_id: str) -> None:
        def _update() -> Any:
            return (
                self._db.table("offers").update({"status": "accepted"}).eq("id", offer_id).execute()
            )

        await self._run(_update)

    async def open_commitment(
        self,
        *,
        operation_id: str,
        offer_id: str,
        participant_segment_id: str,
        audio_offset_ms: int,
        decision_id: str | None = None,
    ) -> str:
        def _insert() -> Any:
            return (
                self._db.table("commitments")
                .insert(
                    {
                        "tenant_id": self._tenant_id,
                        "operation_id": operation_id,
                        "offer_id": offer_id,
                        "participant_segment_id": participant_segment_id,
                        "chain_state": ChainState.VERBAL.value,
                    }
                )
                .execute()
            )

        commitment_id = str((await self._run(_insert)).data[0]["id"])

        # Evidence first. The trigger on commitment_transitions rejects COMMITTED without
        # it, and writing it here means the anchor exists from the very first state.
        def _evidence() -> Any:
            return (
                self._db.table("evidence")
                .insert({"commitment_id": commitment_id, "audio_offset_ms": audio_offset_ms})
                .execute()
            )

        await self._run(_evidence)
        await self._transition_row(
            commitment_id, None, ChainState.VERBAL, "counterparty_confirmed_on_call", decision_id
        )
        return commitment_id

    async def _transition_row(
        self,
        commitment_id: str,
        from_state: str | None,
        to_state: ChainState,
        reason: str,
        decision_id: str | None,
    ) -> None:
        def _insert() -> Any:
            return (
                self._db.table("commitment_transitions")
                .insert(
                    {
                        "commitment_id": commitment_id,
                        "from_state": from_state,
                        "to_state": to_state.value,
                        "reason": reason,
                        "policy_decision_id": decision_id,
                    }
                )
                .execute()
            )

        await self._run(_insert)

    async def transition(
        self,
        commitment_id: str,
        *,
        to_state: ChainState,
        reason: str,
        decision_id: str | None = None,
    ) -> None:
        current = await self.commitment_state(commitment_id)
        await self._transition_row(
            commitment_id, current.value if current else None, to_state, reason, decision_id
        )

        def _update() -> Any:
            return (
                self._db.table("commitments")
                .update({"chain_state": to_state.value})
                .eq("id", commitment_id)
                .execute()
            )

        await self._run(_update)

    async def commitment_state(self, commitment_id: str) -> ChainState | None:
        def _query() -> Any:
            return (
                self._db.table("commitments")
                .select("chain_state")
                .eq("id", commitment_id)
                .limit(1)
                .execute()
            )

        rows = (await self._run(_query)).data or []
        return ChainState(rows[0]["chain_state"]) if rows else None

    async def list_transitions(self, commitment_id: str) -> list[dict[str, Any]]:
        def _query() -> Any:
            return (
                self._db.table("commitment_transitions")
                .select("*")
                .eq("commitment_id", commitment_id)
                .order("occurred_at")
                .execute()
            )

        return list((await self._run(_query)).data or [])

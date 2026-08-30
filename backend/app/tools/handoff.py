"""The controlled handoff capability available to the conversational boundary."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.models import HandoffEvent, HandoffReason, HandoffRequest, HandoffStatus
from app.domain.ports import TranscriptStore
from app.policy import handoff_is_authorized

HandoffExecutor = Callable[[HandoffRequest], Awaitable[None]]


class HandoffTool:
    """Authorizes a proposal, then delegates PSTN work to injected telephony."""

    def __init__(self, store: TranscriptStore, execute: HandoffExecutor) -> None:
        self._store = store
        self._execute = execute

    async def propose_handoff(
        self,
        call_sid: str,
        reason: HandoffReason,
        evidence_offset_ms: int,
        note: str,
    ) -> HandoffRequest | None:
        """Start one handoff per call. It never dials a caller-provided number."""

        if not handoff_is_authorized(reason):
            return None
        request = HandoffRequest(
            handoff_id=uuid4(),
            call_sid=call_sid,
            reason=reason,
            evidence_offset_ms=evidence_offset_ms,
            note=note,
            created_at=datetime.now(UTC),
        )
        if not await self._store.create_handoff(request):
            return None
        await self._store.record_handoff_event(
            HandoffEvent(
                event_key=f"{request.handoff_id}:authorized",
                handoff_id=request.handoff_id,
                status=HandoffStatus.AUTHORIZED,
                created_at=datetime.now(UTC),
            )
        )
        try:
            await self._execute(request)
        except Exception as exc:
            await self._store.record_handoff_event(
                HandoffEvent(
                    event_key=f"{request.handoff_id}:execution-failed",
                    handoff_id=request.handoff_id,
                    status=HandoffStatus.FAILED,
                    detail=type(exc).__name__,
                    created_at=datetime.now(UTC),
                )
            )
            return None
        return request


_DIRECT_REQUEST_PHRASES = (
    "hablar con una persona",
    "hablar con alguien",
    "hablar con un humano",
    "pasame con una persona",
    "pásame con una persona",
    "quiero un supervisor",
    "quiero hablar con un supervisor",
    "speak to a person",
    "speak to someone",
    "human agent",
    "real person",
    "supervisor",
)


def detected_handoff_reason(text: str) -> HandoffReason | None:
    """Conservative deterministic backstop for unmistakable escalation requests."""

    normalized = " ".join(text.casefold().split())
    if any(phrase in normalized for phrase in _DIRECT_REQUEST_PHRASES):
        return HandoffReason.DIRECT_REQUEST
    if "jefe" in normalized and ("autoriz" in normalized or "aprob" in normalized):
        return HandoffReason.OUTSIDE_MANDATE
    if "boss" in normalized and ("approved" in normalized or "authorized" in normalized):
        return HandoffReason.OUTSIDE_MANDATE
    return None

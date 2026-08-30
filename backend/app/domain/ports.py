"""Interfaces the outer layers depend on without importing the inner ones.

``telephony/`` and ``realtime/`` need to persist evidence, but the layering contract
(tests/test_layering.py) forbids them from importing ``repo/`` or ``ledger/``. They take
a ``TranscriptStore`` instead, wired in from the composition root. Same idea for the
model seam: ``agent/`` depends on ``RecapModel``, not on a vendor SDK.
"""

from __future__ import annotations

from typing import Protocol

from app.domain.models import (
    CallBrief,
    CallCase,
    CallDirection,
    HandoffEvent,
    HandoffRequest,
    Recap,
    RecapContext,
    RecapDelivery,
    TranscriptEvent,
)


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


class RecapModel(Protocol):
    """The LLM seam. Given a transcript, return structured content — no side effects."""

    async def summarize(self, transcript: str, context: RecapContext) -> Recap: ...

    async def brief(self, transcript: str) -> CallBrief: ...

    async def handoff_summary(self, request: HandoffRequest, transcript: str) -> str: ...


class RecapSender(Protocol):
    """Delivers the recap by email. Returns the outcome; never raises for a send failure."""

    async def send(self, recap: Recap, to_email: str) -> RecapDelivery: ...


class TranscriptSink(Protocol):
    """What ``realtime/`` calls when a transcript segment is ready. Wired to the ledger."""

    async def __call__(self, event: TranscriptEvent) -> None: ...


class CallCompletedHook(Protocol):
    """What ``telephony/`` calls when Twilio reports a call finished. Wired to RecapService."""

    async def __call__(self, call_sid: str) -> None: ...

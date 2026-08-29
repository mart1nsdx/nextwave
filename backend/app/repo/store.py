"""TranscriptStore implementations.

The Supabase client is synchronous; its calls run in a worker thread so they never block
the event loop that is also pumping a live Media Stream. All database access in the
codebase goes through this module (AGENTS.md) — a Supabase client built anywhere else is
a bug.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from app.config import Settings
from app.domain.models import (
    CallBrief,
    CallCase,
    CallDirection,
    CallStatus,
    Recap,
    RecapDelivery,
    TranscriptEvent,
    TranscriptTrack,
)


def _now() -> datetime:
    return datetime.now(UTC)


class InMemoryTranscriptStore:
    """No network. Used by sim_call and the test suite; behaviour must match Supabase."""

    def __init__(self) -> None:
        self._cases: dict[str, CallCase] = {}
        self._events: dict[str, dict[str, TranscriptEvent]] = {}
        self._recaps: dict[str, Recap] = {}
        self._briefs: dict[str, CallBrief] = {}
        self._deliveries: dict[str, RecapDelivery] = {}

    async def open_case(
        self,
        call_sid: str,
        direction: CallDirection,
        *,
        from_number: str | None = None,
        to_number: str | None = None,
    ) -> None:
        if call_sid in self._cases:  # idempotent — a redelivered 'start' is a no-op
            return
        self._cases[call_sid] = CallCase(
            call_sid=call_sid,
            direction=direction,
            status=CallStatus.ACTIVE,
            from_number=from_number,
            to_number=to_number,
            started_at=_now(),
        )
        self._events.setdefault(call_sid, {})

    async def close_case(self, call_sid: str, *, failed: bool = False) -> None:
        case = self._cases.get(call_sid)
        if case is None or case.status is not CallStatus.ACTIVE:
            return
        case.status = CallStatus.FAILED if failed else CallStatus.ENDED
        case.ended_at = _now()

    async def record_event(self, event: TranscriptEvent) -> None:
        bucket = self._events.setdefault(event.call_sid, {})
        bucket.setdefault(event.event_key, event)  # first write wins; redelivery is a no-op

    async def list_events(self, call_sid: str) -> list[TranscriptEvent]:
        events = self._events.get(call_sid, {}).values()
        return sorted(events, key=lambda e: (e.audio_offset_ms, e.sequence_number))

    async def get_case(self, call_sid: str) -> CallCase | None:
        return self._cases.get(call_sid)

    async def list_cases(self, *, limit: int = 50) -> list[CallCase]:
        cases = sorted(
            self._cases.values(),
            key=lambda c: c.started_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        return cases[:limit]

    async def save_recap(self, recap: Recap) -> None:
        self._recaps[recap.call_sid] = recap

    async def get_recap(self, call_sid: str) -> Recap | None:
        return self._recaps.get(call_sid)

    async def save_brief(self, brief: CallBrief) -> None:
        self._briefs[brief.call_sid] = brief

    async def get_brief(self, call_sid: str) -> CallBrief | None:
        return self._briefs.get(call_sid)

    async def set_recap_delivery(self, delivery: RecapDelivery) -> None:
        self._deliveries[delivery.call_sid] = delivery

    async def get_recap_delivery(self, call_sid: str) -> RecapDelivery | None:
        return self._deliveries.get(call_sid)


class SupabaseTranscriptStore:
    """Backed by the two migrations under supabase/migrations/."""

    def __init__(self, settings: Settings) -> None:
        if not settings.supabase_url or not settings.supabase_secret_key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SECRET_KEY must be set")
        # Imported here so the package has no import-time dependency on the SDK — tests
        # that only touch InMemoryTranscriptStore stay fast and offline.
        from supabase import create_client

        self._db = create_client(settings.supabase_url, settings.supabase_secret_key)
        self._case_ids: dict[str, str] = {}

    async def _run(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def _case_id(self, call_sid: str) -> str | None:
        if call_sid in self._case_ids:
            return self._case_ids[call_sid]

        def _query() -> Any:
            return (
                self._db.table("call_cases")
                .select("id")
                .eq("twilio_call_sid", call_sid)
                .limit(1)
                .execute()
            )

        result = await self._run(_query)
        rows = result.data or []
        if not rows:
            return None
        self._case_ids[call_sid] = rows[0]["id"]
        return self._case_ids[call_sid]

    async def open_case(
        self,
        call_sid: str,
        direction: CallDirection,
        *,
        from_number: str | None = None,
        to_number: str | None = None,
    ) -> None:
        row = {
            "twilio_call_sid": call_sid,
            "direction": direction.value,
            "status": CallStatus.ACTIVE.value,
            "from_number": from_number,
            "to_number": to_number,
        }

        def _upsert() -> Any:
            return (
                self._db.table("call_cases")
                .upsert(row, on_conflict="twilio_call_sid", ignore_duplicates=True)
                .execute()
            )

        await self._run(_upsert)

    async def close_case(self, call_sid: str, *, failed: bool = False) -> None:
        patch = {
            "status": (CallStatus.FAILED if failed else CallStatus.ENDED).value,
            "ended_at": _now().isoformat(),
        }

        def _update() -> Any:
            return (
                self._db.table("call_cases")
                .update(patch)
                .eq("twilio_call_sid", call_sid)
                .eq("status", CallStatus.ACTIVE.value)
                .execute()
            )

        await self._run(_update)

    async def record_event(self, event: TranscriptEvent) -> None:
        case_id = await self._case_id(event.call_sid)
        if case_id is None:
            raise RuntimeError(f"no call_cases row for {event.call_sid!r}; open_case first")
        row = {
            "case_id": case_id,
            "event_key": event.event_key,
            "track": event.track.value,
            "speaker": event.speaker.value,
            "sequence_number": event.sequence_number,
            "audio_offset_ms": event.audio_offset_ms,
            "text": event.text,
            "is_final": event.is_final,
        }

        def _insert() -> Any:
            return (
                self._db.table("call_transcript_events")
                .upsert(row, on_conflict="event_key", ignore_duplicates=True)
                .execute()
            )

        await self._run(_insert)

    async def list_events(self, call_sid: str) -> list[TranscriptEvent]:
        case_id = await self._case_id(call_sid)
        if case_id is None:
            return []

        def _query() -> Any:
            return (
                self._db.table("call_transcript_events")
                .select("*")
                .eq("case_id", case_id)
                .order("audio_offset_ms")
                .order("sequence_number")
                .execute()
            )

        result = await self._run(_query)
        return [
            TranscriptEvent(
                call_sid=call_sid,
                event_key=r["event_key"],
                track=TranscriptTrack(r["track"]),
                speaker=r["speaker"],
                sequence_number=r["sequence_number"],
                audio_offset_ms=r["audio_offset_ms"],
                text=r["text"],
                is_final=r["is_final"],
            )
            for r in (result.data or [])
        ]

    async def get_case(self, call_sid: str) -> CallCase | None:
        def _query() -> Any:
            return (
                self._db.table("call_cases")
                .select("*")
                .eq("twilio_call_sid", call_sid)
                .limit(1)
                .execute()
            )

        result = await self._run(_query)
        rows = result.data or []
        return _case_from_row(rows[0]) if rows else None

    async def list_cases(self, *, limit: int = 50) -> list[CallCase]:
        def _query() -> Any:
            return (
                self._db.table("call_cases")
                .select("*")
                .order("started_at", desc=True)
                .limit(limit)
                .execute()
            )

        result = await self._run(_query)
        return [_case_from_row(r) for r in (result.data or [])]

    async def save_recap(self, recap: Recap) -> None:
        row = recap.model_dump(mode="json")

        def _upsert() -> Any:
            return self._db.table("call_recaps").upsert(row, on_conflict="call_sid").execute()

        await self._run(_upsert)

    async def get_recap(self, call_sid: str) -> Recap | None:
        def _query() -> Any:
            return (
                self._db.table("call_recaps")
                .select("*")
                .eq("call_sid", call_sid)
                .limit(1)
                .execute()
            )

        result = await self._run(_query)
        rows = result.data or []
        return Recap.model_validate(rows[0]) if rows else None

    async def save_brief(self, brief: CallBrief) -> None:
        row = brief.model_dump(mode="json")

        def _upsert() -> Any:
            return self._db.table("call_briefs").upsert(row, on_conflict="call_sid").execute()

        await self._run(_upsert)

    async def get_brief(self, call_sid: str) -> CallBrief | None:
        def _query() -> Any:
            return (
                self._db.table("call_briefs")
                .select("*")
                .eq("call_sid", call_sid)
                .limit(1)
                .execute()
            )

        result = await self._run(_query)
        rows = result.data or []
        return CallBrief.model_validate(rows[0]) if rows else None

    async def set_recap_delivery(self, delivery: RecapDelivery) -> None:
        row = delivery.model_dump(mode="json", exclude_none=True)
        row["updated_at"] = _now().isoformat()

        def _upsert() -> Any:
            return (
                self._db.table("call_recap_deliveries")
                .upsert(row, on_conflict="call_sid")
                .execute()
            )

        await self._run(_upsert)

    async def get_recap_delivery(self, call_sid: str) -> RecapDelivery | None:
        def _query() -> Any:
            return (
                self._db.table("call_recap_deliveries")
                .select("*")
                .eq("call_sid", call_sid)
                .limit(1)
                .execute()
            )

        result = await self._run(_query)
        rows = result.data or []
        return RecapDelivery.model_validate(rows[0]) if rows else None


def _case_from_row(row: dict[str, Any]) -> CallCase:
    return CallCase(
        call_sid=row["twilio_call_sid"],
        direction=CallDirection(row["direction"]),
        status=CallStatus(row["status"]),
        from_number=row.get("from_number"),
        to_number=row.get("to_number"),
        started_at=row.get("started_at"),
        ended_at=row.get("ended_at"),
        metadata=row.get("metadata") or {},
    )

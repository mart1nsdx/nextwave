"""The append-only evidence log for a call.

Append-only is the point (AGENTS.md invariant #4): a later utterance never edits an
earlier one, it appends a new event with its own offset and sequence. A commitment with
no audio offset behind it is EVIDENCE_MISSING, never ``verified`` (#3) — ``has_audio_anchor``
is the check a policy step will call before it lets anything reach COMMITTED.
"""

from __future__ import annotations

from uuid import UUID

from app.domain.models import Speaker, TranscriptEvent, TranscriptTrack, build_event_key
from app.domain.ports import TranscriptStore


class EvidenceLedger:
    """Thin, deterministic wrapper over a TranscriptStore. Holds no state of its own."""

    def __init__(self, store: TranscriptStore) -> None:
        self._store = store

    async def record_segment(
        self,
        call_sid: str,
        *,
        track: TranscriptTrack,
        sequence_number: int,
        audio_offset_ms: int,
        text: str,
        is_final: bool,
        speaker: Speaker = Speaker.UNKNOWN,
        interrupted: bool = False,
        operation_id: UUID | None = None,
        rfq_id: UUID | None = None,
    ) -> TranscriptEvent:
        """Append one transcript segment. Idempotent on what was said and when.

        ``sequence_number`` orders segments that share an offset; it does not identify
        them. Identity is the content-addressed key, so a redelivered segment collapses
        onto the row it already wrote even if the counter behind it has moved on
        (AGENTS.md invariant #7).

        ``operation_id``/``rfq_id`` come from the call's CallBinding. Plumbing the binding
        into the live session is work item W2 and is not on this branch, so they are
        written when the caller has them and left null otherwise — never guessed here.
        """

        event = TranscriptEvent(
            call_sid=call_sid,
            event_key=build_event_key(call_sid, track, audio_offset_ms, text),
            track=track,
            speaker=speaker,
            sequence_number=sequence_number,
            audio_offset_ms=audio_offset_ms,
            text=text,
            is_final=is_final,
            interrupted=interrupted,
            operation_id=operation_id,
            rfq_id=rfq_id,
        )
        await self._store.record_event(event)
        return event

    async def record_event(self, event: TranscriptEvent) -> None:
        """Append a pre-built event. Used when the caller already owns the domain object."""

        await self._store.record_event(event)

    async def transcript(self, call_sid: str, *, finals_only: bool = True) -> list[TranscriptEvent]:
        events = await self._store.list_events(call_sid)
        return [e for e in events if e.is_final] if finals_only else events

    async def transcript_text(self, call_sid: str) -> str:
        """The call as a flat, speaker-labelled script for a model prompt."""

        lines = [
            f"[{e.audio_offset_ms} ms] {e.speaker.value}: {e.text}"
            for e in await self.transcript(call_sid)
        ]
        return "\n".join(lines)

    async def has_audio_anchor(self, call_sid: str) -> bool:
        """True once at least one final transcript event with an offset exists for the call."""

        return any(e.audio_offset_ms >= 0 for e in await self.transcript(call_sid))

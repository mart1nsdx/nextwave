"""FastAPI composition root for the call-evidence and post-call report path."""

import logging

import structlog
from fastapi import FastAPI, HTTPException

from app.agent import OpenAIRecapModel, build_brief, build_recap
from app.config import Settings, get_settings
from app.domain.models import (
    CallBrief,
    CallCase,
    HandoffReason,
    Recap,
    RecapContext,
    Speaker,
    TranscriptEvent,
    TranscriptTrack,
)
from app.domain.ports import RecapModel, TranscriptStore
from app.ledger import EvidenceLedger
from app.repo import InMemoryTranscriptStore, SupabaseTranscriptStore
from app.telephony.handoff import TwilioHandoff
from app.telephony.router import create_router
from app.tools import HandoffTool

log = structlog.get_logger(__name__)


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%H:%M:%S"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )


class RecapService:
    """Generates reports from stored evidence. It never creates a commitment."""

    def __init__(self, ledger: EvidenceLedger, store: TranscriptStore, model: RecapModel) -> None:
        self._ledger = ledger
        self._store = store
        self._model = model

    async def run(self, call_sid: str, *, context: RecapContext | None = None) -> Recap | None:
        transcript = await self._ledger.transcript_text(call_sid)
        if not transcript.strip():
            log.warning("recap_skipped_without_evidence", call_id=call_sid)
            return None
        recap = await build_recap(call_sid, transcript, self._model, context=context)
        brief = await build_brief(call_sid, transcript, self._model)
        await self._store.save_recap(recap)
        await self._store.save_brief(brief)
        return recap


def _build_store(settings: Settings) -> TranscriptStore:
    if settings.supabase_url and settings.supabase_secret_key:
        return SupabaseTranscriptStore(settings)
    log.warning("supabase_unconfigured_using_memory_store")
    return InMemoryTranscriptStore()


def create_app(
    settings: Settings | None = None,
    store: TranscriptStore | None = None,
    recap_model: RecapModel | None = None,
) -> FastAPI:
    configure_logging()
    settings = settings or get_settings()
    store = store or _build_store(settings)
    ledger = EvidenceLedger(store)
    recap_model = recap_model or OpenAIRecapModel(
        settings.openai_api_key,
        settings.openai_recap_model or settings.openai_agent_model,
    )
    recap_service = RecapService(ledger, store, recap_model)
    twilio_handoff = TwilioHandoff(settings, store)
    handoff_tool = HandoffTool(store, twilio_handoff.start)
    sequence_by_call: dict[str, int] = {}

    async def persist_final(
        call_sid: str,
        track: TranscriptTrack,
        speaker: Speaker,
        offset_ms: int,
        text: str,
    ) -> None:
        if not call_sid:
            log.error("transcript_without_call_id")
            return
        if call_sid not in sequence_by_call:
            sequence_by_call[call_sid] = len(await ledger.transcript(call_sid))
        sequence_by_call[call_sid] += 1
        await ledger.record_segment(
            call_sid,
            track=track,
            sequence_number=sequence_by_call[call_sid],
            audio_offset_ms=offset_ms,
            text=text,
            is_final=True,
            speaker=speaker,
        )

    async def complete_call(call_sid: str) -> None:
        try:
            await recap_service.run(call_sid)
        except Exception:
            # A report failure must be visible and must never manufacture a commitment.
            log.exception("recap_generation_failed", call_id=call_sid)

    async def request_handoff(
        call_sid: str, reason: HandoffReason, offset_ms: int, note: str
    ) -> bool:
        return await handoff_tool.propose_handoff(call_sid, reason, offset_ms, note) is not None

    application = FastAPI(title="Volta", version="0.1.0")
    application.state.recap_service = recap_service
    application.include_router(
        create_router(
            settings,
            store,
            complete_call,
            persist_final,
            twilio_handoff,
            request_handoff,
        )
    )

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/calls")
    async def list_calls(limit: int = 50) -> list[CallCase]:
        return await store.list_cases(limit=limit)

    @application.get("/calls/{call_sid}/transcript")
    async def get_transcript(call_sid: str) -> list[TranscriptEvent]:
        events = await store.list_events(call_sid)
        if not events and await store.get_case(call_sid) is None:
            raise HTTPException(status_code=404, detail="call not found")
        return events

    @application.get("/calls/{call_sid}/recap")
    async def get_recap(call_sid: str) -> Recap:
        recap = await store.get_recap(call_sid)
        if recap is None:
            raise HTTPException(status_code=404, detail="recap not generated")
        return recap

    @application.get("/calls/{call_sid}/brief")
    async def get_brief(call_sid: str) -> CallBrief:
        brief = await store.get_brief(call_sid)
        if brief is None:
            raise HTTPException(status_code=404, detail="brief not generated")
        return brief

    @application.post("/calls/{call_sid}/recap")
    async def regenerate_recap(call_sid: str) -> Recap:
        if await store.get_case(call_sid) is None:
            raise HTTPException(status_code=404, detail="call not found")
        recap = await recap_service.run(call_sid)
        if recap is None:
            raise HTTPException(status_code=409, detail="no transcript to summarize")
        return recap

    return application


app = create_app()

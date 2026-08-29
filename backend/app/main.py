"""FastAPI composition root. The only module allowed to import from anywhere.

Wiring lives here so that every other package stays independently testable. This file
assembles the call-evidence path: Twilio audio -> Deepgram transcription -> ledger ->
Supabase, and the post-call recap/brief/email that a dashboard and a policy step read back.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException

from app.agent import OpenAIRecapModel, build_brief, build_recap
from app.config import Settings, get_settings
from app.domain.models import (
    CallBrief,
    CallCase,
    Recap,
    RecapContext,
    RecapDelivery,
    RecapDeliveryStatus,
    TranscriptEvent,
    TranscriptTrack,
)
from app.domain.ports import RecapModel, RecapSender, TranscriptStore
from app.ledger import EvidenceLedger
from app.notify import NullRecapSender, SendGridRecapSender
from app.realtime import RealtimeTranscriber
from app.repo import InMemoryTranscriptStore, SupabaseTranscriptStore
from app.telephony import create_twilio_router

logger = logging.getLogger("volta.main")


class RecapService:
    """Post-call analysis and delivery. Composition-level: it is the only thing that needs
    the ledger, the agent, and notify at once, and none of those may import another."""

    def __init__(
        self,
        ledger: EvidenceLedger,
        store: TranscriptStore,
        model: RecapModel,
        sender: RecapSender,
        *,
        default_to_email: str = "",
    ) -> None:
        self._ledger = ledger
        self._store = store
        self._model = model
        self._sender = sender
        self._default_to_email = default_to_email

    async def run(
        self,
        call_sid: str,
        *,
        context: RecapContext | None = None,
        to_email: str | None = None,
    ) -> Recap | None:
        transcript = await self._ledger.transcript_text(call_sid)
        if not transcript.strip():
            logger.info("no transcript for call=%s; recap skipped", call_sid)
            return None

        recap = await build_recap(call_sid, transcript, self._model, context=context)
        brief = await build_brief(call_sid, transcript, self._model)
        await self._store.save_recap(recap)
        await self._store.save_brief(brief)

        delivery = await self._sender.send(recap, to_email or self._default_to_email)
        await self._store.set_recap_delivery(delivery)
        if delivery.status is RecapDeliveryStatus.SENT:
            logger.info("recap emailed call=%s to=%s", call_sid, delivery.to_email)
        else:
            logger.warning("recap delivery failed call=%s error=%s", call_sid, delivery.error)
        return recap


def _build_store(settings: Settings) -> TranscriptStore:
    if settings.supabase_url and settings.supabase_service_role_key:
        return SupabaseTranscriptStore(settings)
    logger.warning("SUPABASE_* not set — using in-memory store (evidence is not persisted)")
    return InMemoryTranscriptStore()


def _build_sender(settings: Settings) -> RecapSender:
    if settings.sendgrid_api_key and settings.recap_from_email:
        return SendGridRecapSender(settings)
    logger.warning("SENDGRID_API_KEY / RECAP_FROM_EMAIL not set — recap email disabled")
    return NullRecapSender()


def create_app(
    settings: Settings | None = None,
    store: TranscriptStore | None = None,
    recap_model: RecapModel | None = None,
    recap_sender: RecapSender | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    store = store or _build_store(settings)
    ledger = EvidenceLedger(store)
    recap_model = recap_model or OpenAIRecapModel(
        settings.openai_api_key, settings.openai_recap_model
    )
    recap_sender = recap_sender or _build_sender(settings)
    recap_service = RecapService(
        ledger, store, recap_model, recap_sender, default_to_email=settings.recap_to_email
    )

    def make_transcriber(call_sid: str, track: TranscriptTrack) -> RealtimeTranscriber:
        async def sink(event: TranscriptEvent) -> None:
            await ledger.record_event(event)

        return RealtimeTranscriber(
            api_key=settings.deepgram_api_key,
            model=settings.deepgram_model,
            language=settings.deepgram_language,
            call_sid=call_sid,
            track=track,
            on_event=sink,
        )

    async def on_call_completed(call_sid: str) -> None:
        await recap_service.run(call_sid)

    application = FastAPI(title="Volta", version="0.1.0")
    application.state.recap_service = recap_service
    application.include_router(
        create_twilio_router(
            settings,
            store=store,
            make_transcriber=make_transcriber,
            on_call_completed=on_call_completed,
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

    @application.get("/calls/{call_sid}/recap-delivery")
    async def get_recap_delivery(call_sid: str) -> RecapDelivery:
        delivery = await store.get_recap_delivery(call_sid)
        if delivery is None:
            raise HTTPException(status_code=404, detail="recap not yet processed")
        return delivery

    @application.post("/calls/{call_sid}/recap")
    async def regenerate_recap(call_sid: str, to_email: str | None = None) -> Recap:
        if await store.get_case(call_sid) is None:
            raise HTTPException(status_code=404, detail="call not found")
        recap = await recap_service.run(call_sid, to_email=to_email)
        if recap is None:
            raise HTTPException(status_code=409, detail="no transcript to summarize")
        return recap

    return application


app = create_app()

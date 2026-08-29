"""Twilio edge: inbound call webhook, Media Streams receiver, call-status callback.

Every handler is idempotent and keyed on CallSid/StreamSid — Twilio redelivers webhooks
and a second delivery must be a no-op (AGENTS.md invariant #7).

This module owns the PSTN transport only. It never imports repo/ or ledger/: it is handed
a ``TranscriptStore`` and a transcriber factory by the composition root.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse
from xml.sax.saxutils import escape

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from twilio.request_validator import RequestValidator

from app.config import Settings
from app.domain.models import CallDirection, TranscriptTrack
from app.domain.ports import CallCompletedHook, TranscriptStore
from app.realtime import RealtimeTranscriber

logger = logging.getLogger("volta.telephony")

TranscriberFactory = Callable[[str, TranscriptTrack], RealtimeTranscriber]

_ENDED_STATUSES = {"completed", "failed", "busy", "no-answer", "canceled"}


def _public_url(settings: Settings, path: str, *, websocket: bool = False) -> str:
    if not settings.public_base_url:
        raise RuntimeError("PUBLIC_BASE_URL must contain the public HTTPS domain")
    parsed = urlparse(settings.public_base_url)
    return parsed._replace(
        scheme="wss" if websocket else "https",
        path=path,
        params="",
        query="",
        fragment="",
    ).geturl()


def _direction(raw: str) -> CallDirection:
    return CallDirection.OUTBOUND if raw.startswith("outbound") else CallDirection.INBOUND


def _inbound_twiml(settings: Settings) -> str:
    media_url = escape(_public_url(settings, "/twilio/media", websocket=True))
    status_url = escape(_public_url(settings, "/twilio/stream-status"))
    stream = (
        '<Start><Stream name="volta-transcription" '
        f'url="{media_url}" track="both_tracks" statusCallback="{status_url}" />'
        "</Start>"
    )
    if settings.forward_to_number:
        follow = f"<Dial>{escape(settings.forward_to_number)}</Dial>"
    else:
        follow = '<Say>Please hold while we connect your call.</Say><Pause length="600" />'
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{stream}{follow}</Response>'


def create_twilio_router(
    settings: Settings,
    *,
    store: TranscriptStore,
    make_transcriber: TranscriberFactory,
    on_call_completed: CallCompletedHook,
) -> APIRouter:
    router = APIRouter(prefix="/twilio", tags=["telephony"])
    validator = RequestValidator(settings.twilio_auth_token) if settings.twilio_auth_token else None

    async def verify(request: Request) -> dict[str, str]:
        form = {k: str(v) for k, v in (await request.form()).items()}
        if not settings.validate_twilio_signature:
            logger.warning("twilio signature verification disabled")
            return form
        if validator is None:
            raise HTTPException(status_code=500, detail="TWILIO_AUTH_TOKEN is not configured")
        signature = request.headers.get("x-twilio-signature", "")
        url = _public_url(settings, request.url.path)
        if not validator.validate(url, form, signature):
            raise HTTPException(status_code=403, detail="invalid Twilio signature")
        return form

    @router.post("/voice")
    async def voice(request: Request) -> Response:
        form = await verify(request)
        call_sid = form.get("CallSid", "")
        if call_sid:
            await store.open_case(
                call_sid,
                _direction(form.get("Direction", "inbound")),
                from_number=form.get("From"),
                to_number=form.get("To"),
            )
        return Response(_inbound_twiml(settings), media_type="application/xml")

    @router.post("/stream-status")
    async def stream_status(request: Request) -> dict[str, str]:
        form = await verify(request)
        logger.info(
            "stream event=%s call=%s stream=%s error=%s",
            form.get("StreamEvent"),
            form.get("CallSid"),
            form.get("StreamSid"),
            form.get("StreamError", ""),
        )
        return {"status": "ok"}

    @router.post("/call-status")
    async def call_status(request: Request) -> dict[str, str]:
        form = await verify(request)
        call_sid = form.get("CallSid", "")
        status = form.get("CallStatus", "")
        if call_sid and status in _ENDED_STATUSES:
            await store.close_case(call_sid, failed=status != "completed")
            await on_call_completed(call_sid)
        return {"status": "ok"}

    @router.websocket("/media")
    async def media(websocket: WebSocket) -> None:
        await websocket.accept()
        call_sid = "unknown"
        transcribers: dict[TranscriptTrack, RealtimeTranscriber] = {}

        async def transcriber_for(track: TranscriptTrack) -> RealtimeTranscriber:
            existing = transcribers.get(track)
            if existing is not None:
                return existing
            created = make_transcriber(call_sid, track)
            await created.start()
            transcribers[track] = created
            return created

        try:
            while True:
                message: dict[str, Any] = await websocket.receive_json()
                event = message.get("event")
                if event == "start":
                    call_sid = message["start"]["callSid"]
                    logger.info("media stream started call=%s", call_sid)
                elif event == "media":
                    payload = message["media"]
                    track = (
                        TranscriptTrack.OUTBOUND
                        if payload.get("track") == "outbound"
                        else TranscriptTrack.INBOUND
                    )
                    transcriber = await transcriber_for(track)
                    await transcriber.feed(
                        base64.b64decode(payload["payload"]),
                        int(payload.get("timestamp", 0)),
                    )
                elif event == "stop":
                    logger.info("media stream stopped call=%s", call_sid)
                    break
        except WebSocketDisconnect:
            logger.info("media websocket disconnected call=%s", call_sid)
        finally:
            for transcriber in transcribers.values():
                await transcriber.close()

    return router

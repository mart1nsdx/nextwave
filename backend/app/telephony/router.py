"""The Twilio edge, wired to the voice pipeline through injected callbacks."""

from collections.abc import Awaitable, Callable

import structlog
from fastapi import APIRouter, HTTPException, Request, Response, WebSocket
from pydantic import BaseModel, Field

from app.config import Settings
from app.domain.models import CallDirection
from app.domain.ports import TranscriptStore
from app.voice.session import FinalTranscriptSink, build_session

from .idempotency import SeenEvents
from .outbound import place_call
from .stream import MediaStreamTransport
from .twiml import connect_stream, websocket_url

log = structlog.get_logger(__name__)
CallFinished = Callable[[str], Awaitable[None]]


def _direction(value: str) -> CallDirection:
    return CallDirection.OUTBOUND if value.startswith("outbound") else CallDirection.INBOUND


def create_router(
    settings: Settings,
    store: TranscriptStore,
    on_call_finished: CallFinished,
    on_final_transcript: FinalTranscriptSink,
) -> APIRouter:
    """Create the sole Twilio router. It keeps Twilio out of the evidence layers."""
    router = APIRouter(tags=["telephony"])
    seen_status_events = SeenEvents()

    async def finalize_call(call_sid: str, *, failed: bool = False) -> None:
        """Close and report once whether Twilio sends status or only closes media."""
        if not call_sid or not seen_status_events.record(f"{call_sid}:finalized"):
            return
        await store.close_case(call_sid, failed=failed)
        await on_call_finished(call_sid)

    @router.post("/twilio/voice")
    async def voice(request: Request) -> Response:
        form = await request.form()
        call_sid = str(form.get("CallSid", ""))
        if call_sid:
            await store.open_case(
                call_sid,
                _direction(str(form.get("Direction", "inbound"))),
                from_number=str(form.get("From", "")) or None,
                to_number=str(form.get("To", "")) or None,
            )
        log.info("call_connected", call_id=call_sid)
        return Response(
            content=connect_stream(websocket_url(settings.public_base_url)),
            media_type="application/xml",
        )

    @router.post("/twilio/status")
    async def status(request: Request) -> Response:
        form = await request.form()
        call_sid = str(form.get("CallSid", ""))
        call_status = str(form.get("CallStatus", ""))
        if not seen_status_events.record(f"{call_sid}:{call_status}"):
            return Response(status_code=204)
        if call_sid and call_status in {"completed", "failed", "busy", "no-answer", "canceled"}:
            await finalize_call(call_sid, failed=call_status != "completed")
        return Response(status_code=204)

    @router.websocket("/twilio/media")
    async def media(websocket: WebSocket) -> None:
        await websocket.accept()
        transport = MediaStreamTransport(websocket)
        session = build_session(settings, on_final_transcript=on_final_transcript)
        await transport.pump_with(lambda active: session.run(active, active))
        await finalize_call(transport.call_id)

    @router.post("/twilio/voice/echo")
    async def voice_echo() -> Response:
        stream_url = websocket_url(settings.public_base_url, "/twilio/media/echo")
        return Response(content=connect_stream(stream_url), media_type="application/xml")

    @router.websocket("/twilio/media/echo")
    async def media_echo(websocket: WebSocket) -> None:
        await websocket.accept()
        await MediaStreamTransport(websocket).pump_with(echo)

    @router.post("/calls")
    async def start_call(request: CallRequest) -> dict[str, str]:
        try:
            call_sid = await place_call(request.to, settings)
        except ValueError as missing:
            raise HTTPException(status_code=503, detail=str(missing)) from missing
        return {"call_id": call_sid}

    return router


async def echo(transport: MediaStreamTransport) -> None:
    async for frame in transport.frames():
        await transport.send_audio(frame.payload)


class CallRequest(BaseModel):
    to: str = Field(pattern=r"^\+[1-9]\d{7,14}$")

"""The Twilio edge, wired to the voice pipeline through injected callbacks."""

from collections.abc import Awaitable, Callable

import structlog
from fastapi import APIRouter, HTTPException, Request, Response, WebSocket
from pydantic import BaseModel, Field

from app.config import Settings
from app.domain.models import CallDirection, HandoffEvent, HandoffReason, HandoffStatus
from app.domain.ports import TranscriptStore
from app.voice.session import FinalTranscriptSink, VoiceSession

from .handoff import TwilioHandoff
from .idempotency import SeenEvents
from .outbound import place_call
from .stream import MediaStreamTransport
from .twiml import (
    connect_stream,
    handoff_wait,
    operator_brief,
    operator_join_conference,
    unavailable_handoff,
    websocket_url,
)

log = structlog.get_logger(__name__)
CallFinished = Callable[[str], Awaitable[None]]

# Builds the conversation for one call. It takes the direction because that is what
# decides the phase, and it is a callback rather than an import because telephony/ may not
# reach agent/ — the prompt is composed in the composition root and handed down.
SessionFactory = Callable[[CallDirection], VoiceSession]


def _direction(value: str) -> CallDirection:
    return CallDirection.OUTBOUND if value.startswith("outbound") else CallDirection.INBOUND


def create_router(
    settings: Settings,
    store: TranscriptStore,
    on_call_finished: CallFinished,
    on_final_transcript: FinalTranscriptSink,
    handoff: TwilioHandoff,
    on_handoff: Callable[[str, HandoffReason, int, str], Awaitable[bool]],
    make_session: SessionFactory,
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

        async def converse(active: MediaStreamTransport) -> None:
            # Built after `start`, not before: which conversation this is depends on who
            # called whom, and the CallSid that answers that only arrives with the stream.
            # Twilio sends `start` immediately, so this costs no audible delay.
            await active.wait_until_started()
            if not active.call_id:
                return  # the line dropped before it began; no session to open
            case = await store.get_case(active.call_id)
            direction = case.direction if case is not None else CallDirection.INBOUND
            await make_session(direction).run(active, active)

        await transport.pump_with(converse)
        active_handoff = await store.get_handoff_for_call(transport.call_id)
        if active_handoff is None or active_handoff.status not in {
            HandoffStatus.CALLER_ON_HOLD,
            HandoffStatus.HUMAN_DIALING,
            HandoffStatus.CONNECTED,
        }:
            await finalize_call(transport.call_id)

    @router.post("/twilio/voice/echo")
    async def voice_echo() -> Response:
        stream_url = websocket_url(settings.public_base_url, "/twilio/media/echo")
        return Response(content=connect_stream(stream_url), media_type="application/xml")

    @router.websocket("/twilio/media/echo")
    async def media_echo(websocket: WebSocket) -> None:
        await websocket.accept()
        await MediaStreamTransport(websocket).pump_with(echo)

    @router.post("/twilio/handoff/{handoff_id}/wait")
    async def handoff_waiting(handoff_id: str) -> Response:
        base = settings.public_base_url.rstrip("/")
        return Response(
            content=handoff_wait(f"{base}/twilio/handoff/{handoff_id}/wait"),
            media_type="application/xml",
        )

    @router.post("/twilio/handoff/{handoff_id}/brief")
    async def handoff_brief(handoff_id: str) -> Response:
        request = await store.get_handoff(handoff_id)
        if request is None:
            return Response(content=unavailable_handoff(), media_type="application/xml")
        base = settings.public_base_url.rstrip("/")
        message = (
            f"Volta solicita handoff. Razón: {request.reason.value}. "
            f"Nota: {request.note}. No hay ningún compromiso confirmado. "
            "Marque uno para aceptar y unirse al carrier."
        )
        return Response(
            content=operator_brief(f"{base}/twilio/handoff/{handoff_id}/accept", message),
            media_type="application/xml",
        )

    @router.post("/twilio/handoff/{handoff_id}/accept")
    async def handoff_accept(handoff_id: str, request: Request) -> Response:
        handoff_request = await store.get_handoff(handoff_id)
        if handoff_request is None:
            return Response(content=unavailable_handoff(), media_type="application/xml")
        form = await request.form()
        if str(form.get("Digits", "")) != "1" or not handoff_request.conference_name:
            await handoff.fail(handoff_id, "operator declined or timed out")
            return Response(content=unavailable_handoff(), media_type="application/xml")
        await store.record_handoff_event(
            HandoffEvent(
                event_key=f"{handoff_id}:connected",
                handoff_id=handoff_request.handoff_id,
                status=HandoffStatus.CONNECTED,
                detail="operator accepted with DTMF",
            )
        )
        base = settings.public_base_url.rstrip("/")
        return Response(
            content=operator_join_conference(
                handoff_request.conference_name,
                f"{base}/twilio/handoff/{handoff_id}/conference",
            ),
            media_type="application/xml",
        )

    @router.post("/twilio/handoff/{handoff_id}/operator-status")
    async def handoff_operator_status(handoff_id: str, request: Request) -> Response:
        form = await request.form()
        handoff_request = await store.get_handoff(handoff_id)
        operator_status = str(form.get("CallStatus", ""))
        accepted = handoff_request is not None and handoff_request.status is HandoffStatus.CONNECTED
        if operator_status in {"busy", "failed", "no-answer", "canceled"} or (
            operator_status == "completed" and not accepted
        ):
            await handoff.fail(handoff_id, f"operator call {operator_status}")
        return Response(status_code=204)

    @router.post("/twilio/handoff/{handoff_id}/conference")
    async def handoff_conference_status(handoff_id: str, request: Request) -> Response:
        handoff_request = await store.get_handoff(handoff_id)
        form = await request.form()
        conference_ended = str(form.get("StatusCallbackEvent", "")) == "conference-end"
        if handoff_request is not None and conference_ended:
            await store.record_handoff_event(
                HandoffEvent(
                    event_key=f"{handoff_id}:completed",
                    handoff_id=handoff_request.handoff_id,
                    status=HandoffStatus.COMPLETED,
                    detail="conference ended",
                )
            )
        return Response(status_code=204)

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

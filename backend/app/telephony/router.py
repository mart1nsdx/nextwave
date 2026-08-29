"""The PSTN edge: inbound call webhook, the media WebSocket, and status callbacks."""

import structlog
from fastapi import APIRouter, Request, Response, WebSocket

from app.config import get_settings
from app.voice.session import build_session

from .idempotency import SeenEvents
from .stream import MediaStreamTransport
from .twiml import connect_stream, websocket_url

log = structlog.get_logger(__name__)

router = APIRouter(tags=["telephony"])

_seen_status_events = SeenEvents()


@router.post("/twilio/voice")
async def voice(request: Request) -> Response:
    """Twilio's webhook for a call that just connected, inbound or outbound.

    Answers with TwiML that hands the audio to our WebSocket. Returning anything else —
    including an error page — means the caller hears silence and hangs up, so this
    handler does as little as possible and cannot fail on a missing field.
    """
    form = await request.form()
    call_sid = str(form.get("CallSid", ""))
    log.info(
        "call_connected",
        call_id=call_sid,
        from_number=str(form.get("From", "")),
        to_number=str(form.get("To", "")),
        direction=str(form.get("Direction", "")),
    )
    stream_url = websocket_url(get_settings().public_base_url)
    return Response(content=connect_stream(stream_url), media_type="application/xml")


@router.post("/twilio/status")
async def status(request: Request) -> Response:
    """Call lifecycle callbacks. Twilio retries these, so the guard is the point."""
    form = await request.form()
    call_sid = str(form.get("CallSid", ""))
    call_status = str(form.get("CallStatus", ""))

    if not _seen_status_events.record(f"{call_sid}:{call_status}"):
        log.info("status_redelivered", call_id=call_sid, call_status=call_status)
        return Response(status_code=204)

    log.info("call_status", call_id=call_sid, call_status=call_status)
    return Response(status_code=204)


@router.websocket("/twilio/media")
async def media(websocket: WebSocket) -> None:
    """The live audio socket. One connection per call, for the life of the call."""
    await websocket.accept()
    transport = MediaStreamTransport(websocket)
    session = build_session(get_settings())
    # The transport is both ends: it is the AudioSource the pipeline listens to and the
    # AudioSink it speaks into.
    await transport.pump_with(lambda active: session.run(active, active))


@router.post("/twilio/voice/echo")
async def voice_echo(request: Request) -> Response:
    """Same as /twilio/voice, but routed to the echo diagnostic instead of the agent."""
    stream_url = websocket_url(get_settings().public_base_url, "/twilio/media/echo")
    return Response(content=connect_stream(stream_url), media_type="application/xml")


@router.websocket("/twilio/media/echo")
async def media_echo(websocket: WebSocket) -> None:
    await websocket.accept()
    await MediaStreamTransport(websocket).pump_with(echo)


async def echo(transport: MediaStreamTransport) -> None:
    """Play the counterparty's own audio back to them.

    A diagnostic, and the first milestone: it proves the socket, the framing and the
    mu-law round trip in isolation, with no speech vendor in the way. Worth keeping once
    the pipeline replaces it — when the agent sounds wrong at hour 20, this answers in
    one call whether the problem is the phone leg or everything downstream of it.
    """
    async for frame in transport.frames():
        await transport.send_audio(frame.payload)

"""FastAPI entry point for inbound Twilio calls and Media Streams."""

from __future__ import annotations

import base64
import logging
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from twilio.request_validator import RequestValidator

from .config import Settings
from .services.transcriber import AudioFrame, LoggingTranscriber, StreamingTranscriber
from .twiml import inbound_call_twiml

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nextwave.voice")

app = FastAPI(title="Nextwave voice service")
settings = Settings.from_environment()
transcriber: StreamingTranscriber = LoggingTranscriber()


def twilio_validator() -> RequestValidator:
    if not settings.twilio_auth_token:
        raise HTTPException(status_code=500, detail="TWILIO_AUTH_TOKEN is not configured")
    return RequestValidator(settings.twilio_auth_token)


async def verify_webhook(request: Request) -> None:
    if not settings.validate_twilio_signature:
        logger.warning("Twilio signature verification is disabled")
        return
    signature = request.headers.get("x-twilio-signature", "")
    form = await request.form()
    if not twilio_validator().validate(settings.url_for(request.url.path), dict(form), signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


def verify_websocket(websocket: WebSocket) -> bool:
    if not settings.validate_twilio_signature:
        logger.warning("Twilio WebSocket signature verification is disabled")
        return True
    signature = websocket.headers.get("x-twilio-signature", "")
    return bool(signature and twilio_validator().validate(settings.url_for(websocket.url.path, websocket=True), {}, signature))


@app.post("/voice")
async def voice(request: Request) -> Response:
    await verify_webhook(request)
    return Response(inbound_call_twiml(settings), media_type="application/xml")


@app.post("/stream-status")
async def stream_status(request: Request) -> dict[str, str]:
    await verify_webhook(request)
    form = await request.form()
    logger.info("stream event=%s call=%s stream=%s error=%s", form.get("StreamEvent"), form.get("CallSid"), form.get("StreamSid"), form.get("StreamError", ""))
    return {"status": "ok"}


@app.websocket("/media")
async def media(websocket: WebSocket) -> None:
    if not verify_websocket(websocket):
        await websocket.close(code=1008, reason="Invalid Twilio signature")
        return
    await websocket.accept()
    call_sid = "unknown"
    try:
        while True:
            message: dict[str, Any] = await websocket.receive_json()
            if message.get("event") == "start":
                call_sid = message["start"]["callSid"]
                logger.info("call stream started call=%s", call_sid)
            elif message.get("event") == "media":
                media_data = message["media"]
                await transcriber.push(AudioFrame(
                    call_sid=call_sid,
                    track=media_data.get("track", "inbound"),
                    timestamp_ms=media_data.get("timestamp"),
                    mulaw_8khz=base64.b64decode(media_data["payload"]),
                ))
            elif message.get("event") == "stop":
                logger.info("call stream stopped call=%s", call_sid)
                await transcriber.close(call_sid)
                return
    except WebSocketDisconnect:
        logger.info("media WebSocket disconnected call=%s", call_sid)
        await transcriber.close(call_sid)

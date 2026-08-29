"""Placing a real call. The only code here that spends money.

Twilio's REST client is synchronous, so it runs in a worker thread rather than blocking
the event loop that is currently carrying other calls' audio.
"""

import asyncio

import structlog
from twilio.rest import Client

from app.config import Settings

from .twiml import websocket_url

log = structlog.get_logger(__name__)


async def place_call(to_number: str, settings: Settings) -> str:
    """Dial a number and hand the call to the agent. Returns Twilio's call SID.

    Twilio fetches TwiML from `url` once the callee answers, which routes into the same
    /twilio/voice handler an inbound call uses — one audio path, not two.
    """
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        raise ValueError("Twilio credentials are empty — cannot place a call.")
    if not settings.twilio_phone_number:
        raise ValueError("TWILIO_PHONE_NUMBER is empty — there is no number to call from.")
    # Raises if PUBLIC_BASE_URL is unset: better here than after the callee picks up
    # and hears silence.
    websocket_url(settings.public_base_url)

    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    base = settings.public_base_url.rstrip("/")

    call = await asyncio.to_thread(
        client.calls.create,
        to=to_number,
        from_=settings.twilio_phone_number,
        url=f"{base}/twilio/voice",
        status_callback=f"{base}/twilio/status",
        status_callback_event=["initiated", "answered", "completed"],
    )
    log.info("call_placed", call_id=call.sid, to_number=to_number)
    return str(call.sid)

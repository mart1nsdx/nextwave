"""Placing a real call. The only code here that spends money.

Twilio's REST client is synchronous, so it runs in a worker thread rather than blocking
the event loop that is currently carrying other calls' audio.
"""

import asyncio
from urllib.parse import quote

import structlog
from twilio.rest import Client

from app.config import Settings

from .twiml import websocket_url

log = structlog.get_logger(__name__)


async def place_call(to_number: str, settings: Settings, *, case_id: str) -> str:
    """Dial a number and hand the call to the agent. Returns Twilio's call SID.

    Twilio fetches TwiML from `url` once the callee answers, which routes into the same
    /twilio/voice handler an inbound call uses — one audio path, not two.

    `case_id` goes on that URL's query string because /twilio/voice has to render the
    <Stream> before it can know anything else about this call: the CallSid in the webhook
    form is the only other identifier available there, and correlating on it means racing
    our own database write. The case id is on the URL we constructed, so there is nothing
    to race. It is required, not optional: a call this system places with no case behind
    it is exactly the unauthorized call the mandate exists to prevent.
    """
    if not case_id:
        raise ValueError("case_id is empty — refusing to dial a call with no case behind it.")
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
        url=f"{base}/twilio/voice?case_id={quote(case_id, safe='')}",
        status_callback=f"{base}/twilio/status",
        status_callback_event=["initiated", "answered", "completed"],
    )
    log.info("call_placed", call_id=call.sid, to_number=to_number)
    return str(call.sid)

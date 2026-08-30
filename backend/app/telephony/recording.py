"""Recording the call, so that an audio offset points at something a human can hear.

Every commitment stores the millisecond it was agreed at. Until this module existed there
was no audio behind that number: the offset was real, the recording was not, and
"play it back at 04:12" — the one moment in the demo that proves the evidence chain rather
than describing it — had nothing to play.

Recording is started over REST rather than with `<Record>` because the call is already
inside `<Connect><Stream>`, which is terminal TwiML: nothing after it runs. Starting it as
a separate REST action is the supported way to record a call that is being streamed, and
it has the useful property of working identically for inbound and outbound legs.
"""

from __future__ import annotations

import asyncio

import structlog
from twilio.rest import Client

from app.config import Settings

log = structlog.get_logger(__name__)


async def start_recording(call_sid: str, settings: Settings) -> str | None:
    """Begin recording an in-progress call. Returns Twilio's recording SID.

    Never raises. A call that cannot be recorded is worth less as evidence but is still
    worth having — dropping the conversation because the recorder failed would trade a
    real negotiation for a missing artifact.
    """
    if not (settings.twilio_account_sid and settings.twilio_auth_token):
        log.warning("recording_skipped_no_credentials", call_id=call_sid)
        return None
    if not settings.public_base_url:
        log.warning("recording_skipped_no_public_base_url", call_id=call_sid)
        return None

    base = settings.public_base_url.rstrip("/")
    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    try:
        recording = await asyncio.to_thread(
            client.calls(call_sid).recordings.create,
            recording_status_callback=f"{base}/twilio/recording",
            recording_status_callback_event=["completed"],
            # Both legs on separate channels: the agent and the counterparty stay
            # separable afterwards, which is what makes a quote attributable to whoever
            # actually said it.
            recording_channels="dual",
        )
    except Exception:
        log.exception("recording_start_failed", call_id=call_sid)
        return None
    log.info("recording_started", call_id=call_sid, recording_id=recording.sid)
    return str(recording.sid)

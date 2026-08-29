"""Twilio: webhooks, Media Streams, barge-in cutoff, warm transfer.

MAY IMPORT:  domain, config, realtime.
IMPORTED BY: main.

Owns the PSTN edge. Every handler here is idempotent and keyed on call_id/event_id —
Twilio redelivers webhooks, and a second delivery must be a no-op (invariant #7).
"""

from app.telephony.twilio_router import TranscriberFactory, create_twilio_router

__all__ = ["TranscriberFactory", "create_twilio_router"]

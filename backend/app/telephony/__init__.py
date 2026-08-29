"""Twilio: webhooks, Media Streams, barge-in cutoff, warm transfer.

MAY IMPORT:  domain, config, voice.
IMPORTED BY: main.

Owns the PSTN edge. Every handler here is idempotent and keyed on call_id/event_id —
Twilio redelivers webhooks, and a second delivery must be a no-op (invariant #7).

stream.py is the adapter between Twilio's WebSocket protocol and the transport-agnostic
Protocols in voice/frames.py. That seam is why voice/ can be tested with no PSTN leg,
and why swapping Twilio for a SIP backend would not touch the pipeline.
"""

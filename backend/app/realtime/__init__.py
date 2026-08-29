"""Streaming STT vendor session (Deepgram).

MAY IMPORT:  domain, config, agent, tools.
IMPORTED BY: telephony.

Vendor boundary for the streaming *session* — distinct from telephony/, which is the
vendor boundary for the *audio transport*. Two providers, two failure modes, two
directories. Model ids come from config (DEEPGRAM_MODEL); never hardcode one here.
"""

from app.realtime.transcriber import RealtimeTranscriber

__all__ = ["RealtimeTranscriber"]

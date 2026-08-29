"""TwiML generation kept separate from HTTP/WebSocket transport."""

from xml.sax.saxutils import escape

from .config import Settings


def inbound_call_twiml(settings: Settings) -> str:
    media_url = escape(settings.url_for("/media", websocket=True))
    status_url = escape(settings.url_for("/stream-status"))
    stream = (
        '<Start><Stream name="live-transcription" '
        f'url="{media_url}" track="both_tracks" statusCallback="{status_url}" />'
        "</Start>"
    )
    if settings.forward_to_number:
        next_action = f"<Dial>{escape(settings.forward_to_number)}</Dial>"
    else:
        next_action = '<Say>Please hold while we connect your call.</Say><Pause length="600" />'
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{stream}{next_action}</Response>'

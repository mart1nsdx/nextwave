"""TwiML responses. The only place this codebase emits XML.

<Connect><Stream> rather than <Start><Stream>: Connect is bidirectional, which is what
lets us send audio back and — crucially — send `clear` to cut the agent off mid-sentence
when the counterparty barges in. <Start> is one-way and could not do that.
"""

from twilio.twiml.voice_response import Connect, VoiceResponse


def connect_stream(websocket_url: str) -> str:
    """TwiML that hands the call's audio to our WebSocket, in both directions.

    Note the call stays up as long as the stream does. There is no <Say> here: every
    word the agent speaks comes from the TTS stream, so that what is said and what is
    logged are the same bytes.
    """
    response = VoiceResponse()
    connect = Connect()
    connect.stream(url=websocket_url)
    response.append(connect)
    return str(response)


def websocket_url(public_base_url: str, path: str = "/twilio/media") -> str:
    """Turn the configured public https:// base into the wss:// URL Twilio dials back.

    Twilio rejects a Stream url that is not wss://, and the ngrok URL changes on every
    restart, so this is derived rather than configured separately — one fewer thing to
    forget to re-point at 3am.
    """
    if not public_base_url:
        # Fail closed (invariant #6). An empty base yields a schemeless Stream url,
        # which Twilio rejects by dropping the stream — the caller just hears silence
        # and hangs up. A loud error here beats a silent failure on the judge's call.
        raise ValueError(
            "PUBLIC_BASE_URL is empty, so there is no wss:// address for Twilio to "
            "stream audio to. Set it to the current ngrok URL — it changes on every "
            "ngrok restart."
        )
    base = public_base_url.rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://") :]
    return base + path

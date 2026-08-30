"""TwiML responses. The only place this codebase emits XML.

<Connect><Stream> rather than <Start><Stream>: Connect is bidirectional, which is what
lets us send audio back and — crucially — send `clear` to cut the agent off mid-sentence
when the counterparty barges in. <Start> is one-way and could not do that.
"""

from twilio.twiml.voice_response import Connect, Dial, Gather, Say, VoiceResponse


def connect_stream(websocket_url: str, *, case_id: str | None = None) -> str:
    """TwiML that hands the call's audio to our WebSocket, in both directions.

    Note the call stays up as long as the stream does. There is no <Say> here: every
    word the agent speaks comes from the TTS stream, so that what is said and what is
    logged are the same bytes.

    `case_id` rides along as a <Parameter>, which Twilio hands back in the Media Streams
    `start` event as `start.customParameters`. That is why the socket knows which
    operation it is negotiating on its very first message: no CallSid correlation, no
    database read, and therefore no window in which the stream is live but unbound.
    It is omitted for an inbound call, which by definition arrives with no case.
    """
    response = VoiceResponse()
    connect = Connect()
    stream = connect.stream(url=websocket_url)
    if case_id:
        stream.parameter(name="case_id", value=case_id)
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


def caller_hold_conference(conference_name: str, wait_url: str, status_url: str) -> str:
    """Move the caller out of the AI stream and into a moderated conference."""

    response = VoiceResponse()
    dial = Dial()
    dial.conference(
        conference_name,
        start_conference_on_enter=False,
        end_conference_on_exit=True,
        wait_url=wait_url,
        status_callback=status_url,
        status_callback_event="start end join leave",
        participant_label="carrier",
        beep=False,
        max_participants=2,
    )
    response.append(dial)
    return str(response)


def operator_brief(accept_url: str, message: str) -> str:
    """Private operator briefing; only an explicit DTMF 1 joins the carrier."""

    response = VoiceResponse()
    gather = Gather(input="dtmf", num_digits=1, timeout=10, action=accept_url, method="POST")
    gather.append(Say(message, language="es-MX"))
    response.append(gather)
    response.say("No recibimos confirmación. Esta solicitud se cerrará.", language="es-MX")
    response.hangup()
    return str(response)


def operator_join_conference(conference_name: str, status_url: str) -> str:
    """Join the accepting human and start the moderated conference."""

    response = VoiceResponse()
    dial = Dial()
    dial.conference(
        conference_name,
        start_conference_on_enter=True,
        end_conference_on_exit=True,
        status_callback=status_url,
        status_callback_event="start end join leave",
        participant_label="operator",
        beep="onEnter",
        max_participants=2,
    )
    response.append(dial)
    return str(response)


def unavailable_handoff() -> str:
    """Do not strand a carrier on hold when a person cannot accept the call."""

    response = VoiceResponse()
    response.say(
        "No logramos conectar con una persona en este momento. Un miembro del equipo le devolverá "
        "la llamada. Gracias.",
        language="es-MX",
    )
    response.hangup()
    return str(response)


def handoff_wait(wait_url: str) -> str:
    """A short loop while the configured operator is being called."""

    response = VoiceResponse()
    response.say("Un momento mientras le conectamos con una persona.", language="es-MX")
    response.redirect(wait_url, method="POST")
    return str(response)

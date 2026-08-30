"""Who may reach the public surface: Twilio at the webhooks, an operator at the API.

The tunnel URL is public during the demo. Everything in this file is the difference
between "a judge can watch the dashboard" and "a stranger can make us dial their phone".
No PSTN leg is ever placed here: POST /calls is proven to reach the dialler by the 503 it
raises on empty Twilio credentials, which happens before any REST call is made.
"""

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from twilio.request_validator import RequestValidator

from app.config import Settings
from app.domain.models import CallDirection
from app.main import create_app
from app.repo import InMemoryTranscriptStore

AUTH_TOKEN = "twilio-auth-token-for-tests"
API_TOKEN = "operator-token-for-tests"
BASE_URL = "https://volta-demo.ngrok.app"
CALL_SID = "CA0123456789abcdef"
STREAM_SID = "MZ0123456789abcdef"

VOICE_FORM = {"CallSid": CALL_SID, "Direction": "inbound", "From": "+523312345678"}


def _client(store: InMemoryTranscriptStore | None = None, **overrides: object) -> TestClient:
    values: dict[str, object] = {
        "twilio_auth_token": AUTH_TOKEN,
        "public_base_url": BASE_URL,
        "internal_api_token": API_TOKEN,
    }
    values.update(overrides)  # a test takes a key away by passing it back empty
    settings = Settings(**values)  # type: ignore[arg-type]
    return TestClient(create_app(settings=settings, store=store or InMemoryTranscriptStore()))


def _signature(path: str, form: dict[str, str], token: str = AUTH_TOKEN) -> str:
    """What Twilio would send: HMAC over the *public* URL plus the sorted form fields."""
    return RequestValidator(token).compute_signature(f"{BASE_URL}{path}", form)


# --- 9.1 Twilio signature -------------------------------------------------------------


def test_correctly_signed_webhook_is_accepted() -> None:
    response = _client().post(
        "/twilio/voice",
        data=VOICE_FORM,
        headers={"X-Twilio-Signature": _signature("/twilio/voice", VOICE_FORM)},
    )
    assert response.status_code == 200
    assert '<Stream url="wss://volta-demo.ngrok.app/twilio/media"' in response.text


def test_unsigned_webhook_is_rejected() -> None:
    assert _client().post("/twilio/voice", data=VOICE_FORM).status_code == 403


def test_webhook_signed_with_the_wrong_token_is_rejected() -> None:
    response = _client().post(
        "/twilio/voice",
        data=VOICE_FORM,
        headers={"X-Twilio-Signature": _signature("/twilio/voice", VOICE_FORM, "not-our-token")},
    )
    assert response.status_code == 403


def test_tampered_body_invalidates_the_signature() -> None:
    """The signature covers the fields, so an attacker cannot swap the number dialled."""
    signature = _signature("/twilio/voice", VOICE_FORM)
    response = _client().post(
        "/twilio/voice",
        data={**VOICE_FORM, "From": "+15550000000"},
        headers={"X-Twilio-Signature": signature},
    )
    assert response.status_code == 403


def test_signature_is_checked_against_the_public_url_not_the_local_one() -> None:
    """The hour-wasting one: ngrok terminates TLS, so request.url is http://testserver.

    A signature over the local URL must fail; only the public URL Twilio actually signed
    is accepted. If this test ever passes for the wrong URL, every live call 403s.
    """
    local = RequestValidator(AUTH_TOKEN).compute_signature(
        "http://testserver/twilio/voice", VOICE_FORM
    )
    response = _client().post(
        "/twilio/voice", data=VOICE_FORM, headers={"X-Twilio-Signature": local}
    )
    assert response.status_code == 403


def test_status_callback_is_validated_too() -> None:
    form = {"CallSid": CALL_SID, "CallStatus": "completed"}
    client = _client()
    assert client.post("/twilio/status", data=form).status_code == 403
    signed = client.post(
        "/twilio/status",
        data=form,
        headers={"X-Twilio-Signature": _signature("/twilio/status", form)},
    )
    assert signed.status_code == 204


def test_disabling_the_flag_skips_validation() -> None:
    """What sim_call and local curl testing rely on."""
    response = _client(validate_twilio_signature=False).post("/twilio/voice", data=VOICE_FORM)
    assert response.status_code == 200


def test_validation_without_an_auth_token_fails_closed() -> None:
    """Invariant #6: a config gap must not degrade into permission."""
    response = _client(twilio_auth_token="").post("/twilio/voice", data=VOICE_FORM)
    assert response.status_code == 503


# --- 9.2 Operator bearer token --------------------------------------------------------


def test_placing_a_call_without_a_token_is_unauthorized() -> None:
    response = _client().post("/calls", json={"to": "+523312345678"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_placing_a_call_with_the_wrong_token_is_unauthorized() -> None:
    response = _client().post(
        "/calls",
        json={"to": "+523312345678"},
        headers={"Authorization": "Bearer operator-token-for-test"},  # one char short
    )
    assert response.status_code == 401


def test_placing_a_call_with_the_token_reaches_the_dialler() -> None:
    """503 here is place_call refusing empty Twilio credentials — past the guard."""
    response = _client().post(
        "/calls",
        json={"to": "+523312345678"},
        headers={"Authorization": f"Bearer {API_TOKEN}"},
    )
    assert response.status_code == 503
    assert "Twilio credentials" in response.json()["detail"]


@pytest.mark.parametrize(
    "path",
    [
        "/calls",
        f"/calls/{CALL_SID}/transcript",
        f"/calls/{CALL_SID}/recap",
        f"/calls/{CALL_SID}/brief",
    ],
)
def test_read_endpoints_require_the_token(path: str) -> None:
    """D44: transcript bodies are not readable by whoever finds the tunnel URL."""
    assert _client().get(path).status_code == 401


def test_read_endpoints_answer_with_the_token() -> None:
    client = _client()
    response = client.get("/calls", headers={"Authorization": f"Bearer {API_TOKEN}"})
    assert response.status_code == 200
    assert response.json() == []


def test_unset_token_refuses_the_dialling_route_rather_than_opening_it() -> None:
    """Unconfigured means closed, both with and without an Authorization header."""
    client = _client(internal_api_token="")
    assert client.post("/calls", json={"to": "+523312345678"}).status_code == 503
    with_header = client.post(
        "/calls", json={"to": "+523312345678"}, headers={"Authorization": "Bearer anything"}
    )
    assert with_header.status_code == 503


def test_health_stays_open() -> None:
    assert _client().get("/health").json() == {"status": "ok"}


# --- 9.3 Media streams ----------------------------------------------------------------


def _start(call_sid: str) -> str:
    message: dict[str, Any] = {
        "event": "start",
        "streamSid": STREAM_SID,
        "start": {"streamSid": STREAM_SID, "callSid": call_sid},
    }
    return json.dumps(message)


def test_media_stream_for_an_unknown_call_is_closed() -> None:
    """A stranger's socket must not buy STT, an LLM and TTS on our account."""
    client = _client()
    with client.websocket_connect("/twilio/media") as socket:
        socket.send_text(_start("CAnot-a-call-we-placed"))
        with pytest.raises(WebSocketDisconnect):
            socket.receive_text()


def test_media_stream_for_a_closed_case_is_closed() -> None:
    """The call already ended: replaying its CallSid does not reopen the pipeline."""
    store = InMemoryTranscriptStore()

    async def ended() -> None:
        await store.open_case(CALL_SID, CallDirection.INBOUND)
        await store.close_case(CALL_SID)

    asyncio.run(ended())
    client = _client(store)
    with client.websocket_connect("/twilio/media") as socket:
        socket.send_text(_start(CALL_SID))
        with pytest.raises(WebSocketDisconnect):
            socket.receive_text()

"""Twilio webhook behaviour: TwiML, case creation, call-status → recap trigger.

Signature validation is disabled here (as it is against a local tunnel); the signature
path itself is exercised in test_twilio_signature.
"""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.models import (
    CallBrief,
    CallDirection,
    Recap,
    RecapContext,
    RecapDelivery,
    RecapDeliveryStatus,
    Speaker,
    TranscriptTrack,
)
from app.ledger import EvidenceLedger
from app.main import create_app
from app.repo import InMemoryTranscriptStore

PUBLIC = "https://sub.ngrok.app"


class StubModel:
    async def summarize(self, transcript: str, context: RecapContext) -> Recap:
        return Recap(call_sid="", summary="stub")

    async def brief(self, transcript: str) -> CallBrief:
        return CallBrief(call_sid="")


class StubSender:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def send(self, recap: Recap, to_email: str) -> RecapDelivery:
        self.calls.append(recap.call_sid)
        return RecapDelivery(call_sid=recap.call_sid, status=RecapDeliveryStatus.SENT)


@pytest.fixture
def wired() -> tuple[TestClient, InMemoryTranscriptStore, StubSender]:
    store = InMemoryTranscriptStore()
    sender = StubSender()
    settings = Settings(validate_twilio_signature=False, public_base_url=PUBLIC)
    app = create_app(settings=settings, store=store, recap_model=StubModel(), recap_sender=sender)
    return TestClient(app), store, sender


def test_voice_webhook_returns_stream_twiml_and_opens_case(
    wired: tuple[TestClient, InMemoryTranscriptStore, StubSender],
) -> None:
    tc, store, _ = wired
    response = tc.post(
        "/twilio/voice",
        data={"CallSid": "CAvoice", "From": "+523301", "To": "+523300", "Direction": "inbound"},
    )
    assert response.status_code == 200
    body = response.text
    assert 'url="wss://sub.ngrok.app/twilio/media"' in body
    assert 'track="both_tracks"' in body

    # case row was created from the webhook form, keyed by phone numbers
    calls = tc.get("/calls").json()
    assert calls[0]["call_sid"] == "CAvoice"
    assert calls[0]["from_number"] == "+523301"


async def test_call_status_completed_triggers_recap(
    wired: tuple[TestClient, InMemoryTranscriptStore, StubSender],
) -> None:
    tc, store, sender = wired

    await store.open_case("CAdone", CallDirection.INBOUND)
    await EvidenceLedger(store).record_segment(
        "CAdone",
        track=TranscriptTrack.INBOUND,
        sequence_number=1,
        audio_offset_ms=1000,
        text="listo",
        is_final=True,
        speaker=Speaker.CALLER,
    )

    response = tc.post("/twilio/call-status", data={"CallSid": "CAdone", "CallStatus": "completed"})
    assert response.status_code == 200
    assert sender.calls == ["CAdone"]
    assert (await store.get_recap("CAdone")) is not None
    delivery = await store.get_recap_delivery("CAdone")
    assert delivery is not None and delivery.status is RecapDeliveryStatus.SENT


def test_call_status_ringing_does_nothing(
    wired: tuple[TestClient, InMemoryTranscriptStore, StubSender],
) -> None:
    tc, _, sender = wired
    tc.post("/twilio/call-status", data={"CallSid": "CAring", "CallStatus": "ringing"})
    assert sender.calls == []


def test_invalid_signature_is_rejected() -> None:
    store = InMemoryTranscriptStore()
    settings = Settings(
        validate_twilio_signature=True,
        twilio_auth_token="secret",
        public_base_url=PUBLIC,
    )
    tc = TestClient(
        create_app(
            settings=settings, store=store, recap_model=StubModel(), recap_sender=StubSender()
        )
    )
    response = tc.post(
        "/twilio/voice", data={"CallSid": "CAx"}, headers={"x-twilio-signature": "wrong"}
    )
    assert response.status_code == 403

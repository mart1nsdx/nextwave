"""Read API + manual recap trigger, wired to an in-memory store and a fake model.

These are the endpoints the dashboard consumes. No network, no OpenAI.
"""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.models import (
    BriefMention,
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


class FakeRecapModel:
    async def summarize(self, transcript: str, context: RecapContext) -> Recap:
        return Recap(call_sid="", summary="held at the cap, escalated", quoted_prices=["9,000 MXN"])

    async def brief(self, transcript: str) -> CallBrief:
        mention = BriefMention(audio_offset_ms=6400, speaker=Speaker.CALLER, detail="9,500 MXN")
        return CallBrief(call_sid="", mentions=[mention])


class FakeRecapSender:
    async def send(self, recap: Recap, to_email: str) -> RecapDelivery:
        return RecapDelivery(
            call_sid=recap.call_sid,
            status=RecapDeliveryStatus.SENT,
            to_email=to_email or "default@example.com",
            provider_message_id="msg_api",
        )


@pytest.fixture
def client() -> tuple[TestClient, InMemoryTranscriptStore]:
    store = InMemoryTranscriptStore()
    app = create_app(
        settings=Settings(),
        store=store,
        recap_model=FakeRecapModel(),
        recap_sender=FakeRecapSender(),
    )
    return TestClient(app), store


async def _seed(store: InMemoryTranscriptStore, call_sid: str = "CAapi1") -> None:
    await store.open_case(call_sid, CallDirection.INBOUND, from_number="+52331", to_number="+52330")
    ledger = EvidenceLedger(store)
    await ledger.record_segment(
        call_sid,
        track=TranscriptTrack.INBOUND,
        sequence_number=1,
        audio_offset_ms=6400,
        text="le sale en nueve mil quinientos",
        is_final=True,
        speaker=Speaker.CALLER,
    )


def test_health(client: tuple[TestClient, InMemoryTranscriptStore]) -> None:
    tc, _ = client
    assert tc.get("/health").json() == {"status": "ok"}


async def test_list_calls_and_transcript(
    client: tuple[TestClient, InMemoryTranscriptStore],
) -> None:
    tc, store = client
    await _seed(store)
    calls = tc.get("/calls").json()
    assert calls[0]["call_sid"] == "CAapi1"
    assert calls[0]["from_number"] == "+52331"
    transcript = tc.get("/calls/CAapi1/transcript").json()
    assert transcript[0]["text"] == "le sale en nueve mil quinientos"
    assert transcript[0]["audio_offset_ms"] == 6400


def test_unknown_call_transcript_is_404(
    client: tuple[TestClient, InMemoryTranscriptStore],
) -> None:
    tc, _ = client
    assert tc.get("/calls/NOPE/transcript").status_code == 404
    assert tc.get("/calls/NOPE/recap").status_code == 404


async def test_recap_generation_and_readback(
    client: tuple[TestClient, InMemoryTranscriptStore],
) -> None:
    tc, store = client
    await _seed(store)

    generated = tc.post("/calls/CAapi1/recap")
    assert generated.status_code == 200
    assert generated.json()["summary"] == "held at the cap, escalated"

    recap = tc.get("/calls/CAapi1/recap").json()
    assert recap["call_sid"] == "CAapi1"
    assert recap["quoted_prices"] == ["9,000 MXN"]

    brief = tc.get("/calls/CAapi1/brief").json()
    assert brief["mentions"][0]["detail"] == "9,500 MXN"

    delivery = tc.get("/calls/CAapi1/recap-delivery").json()
    assert delivery["status"] == "sent"
    assert delivery["provider_message_id"] == "msg_api"


async def test_recap_without_transcript_is_409(
    client: tuple[TestClient, InMemoryTranscriptStore],
) -> None:
    tc, store = client
    await store.open_case("CAempty", CallDirection.INBOUND)
    assert tc.post("/calls/CAempty/recap").status_code == 409

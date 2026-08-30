"""The persisted evidence -> recap -> brief path, without PSTN or external models."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.models import (
    AgreementCandidate,
    BriefMention,
    CallBrief,
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


class FakeReportModel:
    async def summarize(self, transcript: str, context: RecapContext) -> Recap:
        assert "[1200 ms] caller: nueve mil pesos" in transcript
        return Recap(
            call_sid="",
            summary="El carrier cotizó nueve mil pesos.",
            quoted_prices=["9,000 MXN"],
            conditions=["Sujeto a confirmar ventana."],
            agreement_candidates=[
                AgreementCandidate(
                    counterparty="carrier",
                    terms="Nueve mil pesos, sujeto a confirmar ventana.",
                    audio_offset_ms=1200,
                )
            ],
        )

    async def brief(self, transcript: str) -> CallBrief:
        return CallBrief(
            call_sid="",
            mentions=[
                BriefMention(
                    audio_offset_ms=1200,
                    speaker=Speaker.CALLER,
                    detail="Cotización: nueve mil pesos",
                )
            ],
        )


class RecordingSender:
    """Stands in for SendGrid. Records what would have gone out, and to whom."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, recap: Recap, to_email: str) -> RecapDelivery:
        self.sent.append((recap.call_sid, to_email))
        return RecapDelivery(
            call_sid=recap.call_sid, status=RecapDeliveryStatus.SENT, to_email=to_email
        )


async def test_completed_call_generates_reports_from_persisted_evidence() -> None:
    store = InMemoryTranscriptStore()
    app = create_app(
        settings=Settings(public_base_url="https://volta.ngrok.app"),
        store=store,
        recap_model=FakeReportModel(),
    )
    client = TestClient(app)

    response = client.post(
        "/twilio/voice",
        data={"CallSid": "CAreport", "Direction": "inbound", "From": "+523300000001"},
    )
    assert response.status_code == 200

    await EvidenceLedger(store).record_segment(
        "CAreport",
        track=TranscriptTrack.INBOUND,
        sequence_number=1,
        audio_offset_ms=1200,
        text="nueve mil pesos",
        is_final=True,
        speaker=Speaker.CALLER,
    )

    assert (
        client.post(
            "/twilio/status", data={"CallSid": "CAreport", "CallStatus": "completed"}
        ).status_code
        == 204
    )

    transcript = client.get("/calls/CAreport/transcript").json()
    assert transcript[0]["audio_offset_ms"] == 1200
    assert client.get("/calls/CAreport/recap").json()["quoted_prices"] == ["9,000 MXN"]
    assert (
        client.get("/calls/CAreport/recap").json()["agreement_candidates"][0]["audio_offset_ms"]
        == 1200
    )
    assert client.get("/calls/CAreport/brief").json()["mentions"][0]["audio_offset_ms"] == 1200


async def test_a_completed_call_actually_sends_the_recap_and_records_delivery() -> None:
    """The second of the two verifications the brief asks for.

    Generating a recap and storing it proves nothing to a counterparty. Until this test
    existed the app produced recaps that never left the process, and
    ``call_recap_deliveries`` stayed empty on every real call.
    """
    store = InMemoryTranscriptStore()
    sender = RecordingSender()
    app = create_app(
        settings=Settings(
            public_base_url="https://volta.ngrok.app",
            recap_to_email="ops@textilespacifico.mx",
        ),
        store=store,
        recap_model=FakeReportModel(),
        recap_sender=sender,
    )
    client = TestClient(app)
    client.post("/twilio/voice", data={"CallSid": "CAsend", "Direction": "inbound"})
    await EvidenceLedger(store).record_segment(
        "CAsend",
        track=TranscriptTrack.INBOUND,
        sequence_number=1,
        audio_offset_ms=1200,
        text="nueve mil pesos",
        is_final=True,
        speaker=Speaker.CALLER,
    )

    client.post("/twilio/status", data={"CallSid": "CAsend", "CallStatus": "completed"})

    assert sender.sent == [("CAsend", "ops@textilespacifico.mx")]
    delivery = await store.get_recap_delivery("CAsend")
    assert delivery is not None
    assert delivery.status is RecapDeliveryStatus.SENT


async def test_an_unconfigured_recap_channel_fails_loudly_rather_than_silently() -> None:
    """No recipient means FAILED, never a quiet success.

    This is the difference between a commitment that stalls visibly and one that looks
    verified while nothing was ever sent.
    """
    store = InMemoryTranscriptStore()
    app = create_app(
        settings=Settings(public_base_url="https://volta.ngrok.app"),
        store=store,
        recap_model=FakeReportModel(),
        recap_sender=RecordingSender(),
    )
    client = TestClient(app)
    client.post("/twilio/voice", data={"CallSid": "CAnorecip", "Direction": "inbound"})
    await EvidenceLedger(store).record_segment(
        "CAnorecip",
        track=TranscriptTrack.INBOUND,
        sequence_number=1,
        audio_offset_ms=1200,
        text="nueve mil pesos",
        is_final=True,
        speaker=Speaker.CALLER,
    )

    client.post("/twilio/status", data={"CallSid": "CAnorecip", "CallStatus": "completed"})

    delivery = await store.get_recap_delivery("CAnorecip")
    assert delivery is not None
    assert delivery.status is RecapDeliveryStatus.FAILED
    assert delivery.error == "RECAP_TO_EMAIL is not configured"

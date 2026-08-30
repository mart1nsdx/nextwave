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
from app.main import RecapService, create_app
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


class FakeRecapSender:
    """Honours the RecapSender contract: reports the outcome, never raises."""

    def __init__(self, status: RecapDeliveryStatus) -> None:
        self._status = status
        self.sent: list[tuple[str, str]] = []

    async def send(self, recap: Recap, to_email: str) -> RecapDelivery:
        self.sent.append((recap.call_sid, to_email))
        return RecapDelivery(
            call_sid=recap.call_sid,
            status=self._status,
            to_email=to_email or None,
            error=None if self._status is RecapDeliveryStatus.SENT else "sendgrid 500",
        )


async def _record_quote(store: InMemoryTranscriptStore, call_sid: str) -> None:
    await EvidenceLedger(store).record_segment(
        call_sid,
        track=TranscriptTrack.INBOUND,
        sequence_number=1,
        audio_offset_ms=1200,
        text="nueve mil pesos",
        is_final=True,
        speaker=Speaker.CALLER,
    )


def _service(store: InMemoryTranscriptStore, sender: FakeRecapSender) -> RecapService:
    return RecapService(
        EvidenceLedger(store), store, FakeReportModel(), sender, "operaciones@volta.mx"
    )


async def test_recap_run_closes_the_delivery_gate() -> None:
    store = InMemoryTranscriptStore()
    await _record_quote(store, "CAsent")
    sender = FakeRecapSender(RecapDeliveryStatus.SENT)

    assert await _service(store, sender).run("CAsent") is not None

    assert sender.sent == [("CAsent", "operaciones@volta.mx")]
    delivery = await store.get_recap_delivery("CAsent")
    assert delivery is not None
    assert delivery.status is RecapDeliveryStatus.SENT
    assert delivery.to_email == "operaciones@volta.mx"


async def test_failed_delivery_keeps_the_recap_and_never_raises() -> None:
    store = InMemoryTranscriptStore()
    await _record_quote(store, "CAfailed")

    # The recap exists either way; a send failure leaves the invariant-#3 gate red,
    # it does not break the call path and it is never recorded as a skip.
    recap = await _service(store, FakeRecapSender(RecapDeliveryStatus.FAILED)).run("CAfailed")

    assert recap is not None
    assert await store.get_recap("CAfailed") is not None
    delivery = await store.get_recap_delivery("CAfailed")
    assert delivery is not None
    assert delivery.status is RecapDeliveryStatus.FAILED
    assert delivery.error == "sendgrid 500"


async def test_recap_delivery_endpoint_reports_the_gate() -> None:
    store = InMemoryTranscriptStore()
    app = create_app(
        settings=Settings(
            public_base_url="https://volta.ngrok.app", recap_to_email="operaciones@volta.mx"
        ),
        store=store,
        recap_model=FakeReportModel(),
        recap_sender=FakeRecapSender(RecapDeliveryStatus.SENT),
    )
    client = TestClient(app)

    client.post("/twilio/voice", data={"CallSid": "CAgate", "Direction": "inbound"})
    assert client.get("/calls/CAgate/recap-delivery").status_code == 404

    await _record_quote(store, "CAgate")
    assert (
        client.post(
            "/twilio/status", data={"CallSid": "CAgate", "CallStatus": "completed"}
        ).status_code
        == 204
    )

    body = client.get("/calls/CAgate/recap-delivery").json()
    assert body["status"] == "sent"
    assert body["to_email"] == "operaciones@volta.mx"

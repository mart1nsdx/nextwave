"""The persisted evidence -> recap -> brief path, without PSTN or external models."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.models import (
    AgreementCandidate,
    BriefMention,
    CallBrief,
    Recap,
    RecapContext,
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

    assert client.post(
        "/twilio/status", data={"CallSid": "CAreport", "CallStatus": "completed"}
    ).status_code == 204

    transcript = client.get("/calls/CAreport/transcript").json()
    assert transcript[0]["audio_offset_ms"] == 1200
    assert client.get("/calls/CAreport/recap").json()["quoted_prices"] == ["9,000 MXN"]
    assert client.get("/calls/CAreport/recap").json()["agreement_candidates"][0][
        "audio_offset_ms"
    ] == 1200
    assert client.get("/calls/CAreport/brief").json()["mentions"][0]["audio_offset_ms"] == 1200

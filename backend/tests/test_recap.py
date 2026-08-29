"""Recap + brief generation and delivery over injected fakes. No OpenAI, no SendGrid.

The seams are domain.RecapModel and domain.RecapSender; these tests pin the orchestration
(stamping call_sid, wiring the ledger transcript into the prompt, persisting recap, brief,
and delivery status).
"""

from datetime import UTC, datetime

from app.agent import build_brief, build_recap
from app.domain.models import (
    BriefAction,
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
from app.main import RecapService
from app.repo import InMemoryTranscriptStore


class FakeRecapModel:
    def __init__(self) -> None:
        self.seen_transcript: str | None = None

    async def summarize(self, transcript: str, context: RecapContext) -> Recap:
        self.seen_transcript = transcript
        return Recap(
            call_sid="",
            summary="Carrier quoted 9,200; agent held at the 9,000 cap and did not commit.",
            quoted_prices=["9,200 MXN", "9,000 MXN"],
            names=["Juan"],
            objections=["carrier pushed above the cap"],
        )

    async def brief(self, transcript: str) -> CallBrief:
        return CallBrief(
            call_sid="",
            actions=[BriefAction(audio_offset_ms=1200, description="asked for a quote")],
        )


class FakeRecapSender:
    def __init__(self, *, ok: bool = True) -> None:
        self.ok = ok
        self.sent: list[tuple[str, str]] = []

    async def send(self, recap: Recap, to_email: str) -> RecapDelivery:
        self.sent.append((recap.call_sid, to_email))
        if not self.ok:
            return RecapDelivery(
                call_sid=recap.call_sid,
                status=RecapDeliveryStatus.FAILED,
                to_email=to_email,
                error="simulated bounce",
            )
        return RecapDelivery(
            call_sid=recap.call_sid,
            status=RecapDeliveryStatus.SENT,
            to_email=to_email,
            provider_message_id="msg_1",
            sent_at=datetime.now(UTC),
        )


async def _seed_call(store: InMemoryTranscriptStore, call_sid: str = "CA5") -> None:
    await store.open_case(call_sid, CallDirection.INBOUND)
    ledger = EvidenceLedger(store)
    await ledger.record_segment(
        call_sid,
        track=TranscriptTrack.INBOUND,
        sequence_number=1,
        audio_offset_ms=1200,
        text="son nueve mil doscientos",
        is_final=True,
        speaker=Speaker.CALLER,
    )


def _service(store: InMemoryTranscriptStore, sender: FakeRecapSender | None = None) -> RecapService:
    return RecapService(
        EvidenceLedger(store),
        store,
        FakeRecapModel(),
        sender or FakeRecapSender(),
        default_to_email="cliente@textilespacifico.mx",
    )


async def test_build_recap_stamps_call_sid_and_generated_at() -> None:
    recap = await build_recap("CA5", "[1200 ms] caller: hola", FakeRecapModel())
    assert recap.call_sid == "CA5"
    assert recap.generated_at is not None
    assert "9,000 MXN" in recap.quoted_prices


async def test_build_brief_stamps_call_sid() -> None:
    brief = await build_brief("CA5", "transcript", FakeRecapModel())
    assert brief.call_sid == "CA5"
    assert brief.actions[0].description == "asked for a quote"


async def test_recap_service_persists_recap_brief_and_delivery() -> None:
    store = InMemoryTranscriptStore()
    await _seed_call(store)
    sender = FakeRecapSender()
    service = _service(store, sender)

    recap = await service.run("CA5")

    assert recap is not None and recap.call_sid == "CA5"
    assert (await store.get_recap("CA5")) is not None
    assert (await store.get_brief("CA5")) is not None
    assert sender.sent == [("CA5", "cliente@textilespacifico.mx")]
    delivery = await store.get_recap_delivery("CA5")
    assert delivery is not None and delivery.status is RecapDeliveryStatus.SENT


async def test_recap_service_records_failed_delivery() -> None:
    store = InMemoryTranscriptStore()
    await _seed_call(store)
    service = _service(store, FakeRecapSender(ok=False))

    await service.run("CA5", to_email="dispatch@fletes.mx")

    delivery = await store.get_recap_delivery("CA5")
    assert delivery is not None
    assert delivery.status is RecapDeliveryStatus.FAILED
    assert delivery.error == "simulated bounce"
    # the recap itself still exists — only the commitment gate is blocked
    assert (await store.get_recap("CA5")) is not None


async def test_recap_service_skips_when_no_transcript() -> None:
    store = InMemoryTranscriptStore()
    await store.open_case("CA6", CallDirection.INBOUND)
    service = _service(store)

    assert await service.run("CA6") is None
    assert await store.get_recap("CA6") is None
    assert await store.get_recap_delivery("CA6") is None

"""EvidenceLedger + InMemoryTranscriptStore. Pure, offline.

The in-memory store must behave like Supabase for these operations, so these tests double
as the contract every TranscriptStore implementation has to satisfy.
"""

from app.domain.models import CallDirection, Speaker, TranscriptTrack
from app.ledger import EvidenceLedger
from app.repo import InMemoryTranscriptStore


async def _ledger_with_case(
    call_sid: str = "CA1",
) -> tuple[EvidenceLedger, InMemoryTranscriptStore]:
    store = InMemoryTranscriptStore()
    await store.open_case(call_sid, CallDirection.INBOUND, from_number="+521", to_number="+520")
    return EvidenceLedger(store), store


async def test_segments_are_ordered_by_offset() -> None:
    ledger, _ = await _ledger_with_case()
    await ledger.record_segment(
        "CA1",
        track=TranscriptTrack.INBOUND,
        sequence_number=2,
        audio_offset_ms=4000,
        text="segundo",
        is_final=True,
    )
    await ledger.record_segment(
        "CA1",
        track=TranscriptTrack.INBOUND,
        sequence_number=1,
        audio_offset_ms=1000,
        text="primero",
        is_final=True,
    )
    transcript = await ledger.transcript("CA1")
    assert [e.text for e in transcript] == ["primero", "segundo"]


async def test_redelivered_segment_is_a_noop() -> None:
    ledger, store = await _ledger_with_case()
    for _ in range(3):
        await ledger.record_segment(
            "CA1",
            track=TranscriptTrack.INBOUND,
            sequence_number=1,
            audio_offset_ms=1000,
            text="hola",
            is_final=True,
        )
    assert len(await store.list_events("CA1")) == 1


async def test_later_utterance_does_not_edit_an_earlier_one() -> None:
    ledger, _ = await _ledger_with_case()
    await ledger.record_segment(
        "CA1",
        track=TranscriptTrack.INBOUND,
        sequence_number=1,
        audio_offset_ms=1000,
        text="ocho mil quinientos",
        is_final=True,
    )
    await ledger.record_segment(
        "CA1",
        track=TranscriptTrack.INBOUND,
        sequence_number=2,
        audio_offset_ms=9000,
        text="mejor nueve mil doscientos",
        is_final=True,
    )
    texts = [e.text for e in await ledger.transcript("CA1")]
    assert texts == ["ocho mil quinientos", "mejor nueve mil doscientos"]


async def test_has_audio_anchor_reflects_evidence() -> None:
    ledger, _ = await _ledger_with_case()
    assert await ledger.has_audio_anchor("CA1") is False
    await ledger.record_segment(
        "CA1",
        track=TranscriptTrack.INBOUND,
        sequence_number=1,
        audio_offset_ms=0,
        text="bueno",
        is_final=True,
        speaker=Speaker.CALLER,
    )
    assert await ledger.has_audio_anchor("CA1") is True


async def test_transcript_text_is_speaker_labelled() -> None:
    ledger, _ = await _ledger_with_case()
    await ledger.record_segment(
        "CA1",
        track=TranscriptTrack.INBOUND,
        sequence_number=1,
        audio_offset_ms=500,
        text="tengo un camion",
        is_final=True,
        speaker=Speaker.CALLER,
    )
    text = await ledger.transcript_text("CA1")
    assert text == "[500 ms] caller: tengo un camion"


async def test_close_case_is_idempotent() -> None:
    _, store = await _ledger_with_case()
    await store.close_case("CA1")
    first = await store.get_case("CA1")
    assert first is not None and first.status == "ended"
    await store.close_case("CA1", failed=True)  # already ended -> no change
    second = await store.get_case("CA1")
    assert second is not None and second.status == "ended"

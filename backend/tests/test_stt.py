"""The scripted recognizer. No network, no API key, no audio files."""

import asyncio

from app.voice.events import (
    FinalTranscript,
    PartialTranscript,
    SpeechStarted,
    SttEvent,
    UtteranceEnd,
)
from app.voice.frames import FRAME_BYTES, SILENCE_BYTE, InboundFrame
from app.voice.stt.fake import FakeStt, FakeSttSession, ScriptedUtterance

SILENT_FRAME = bytes([SILENCE_BYTE]) * FRAME_BYTES


def _frame(offset_ms: int) -> InboundFrame:
    return InboundFrame(payload=SILENT_FRAME, offset_ms=offset_ms)


async def _drain(session: FakeSttSession, through_ms: int, step_ms: int = 20) -> list[SttEvent]:
    """Feed silence up to a point on the audio clock and collect what came out."""
    collected: list[SttEvent] = []

    async def collect() -> None:
        async for event in session.events():
            collected.append(event)

    task = asyncio.create_task(collect())
    for offset in range(step_ms, through_ms + step_ms, step_ms):
        await session.send(_frame(offset))
    await session.close()
    await task
    return collected


async def test_one_utterance_produces_the_full_event_sequence() -> None:
    session = FakeSttSession([ScriptedUtterance("ocho mil quinientos", 100, 500)])
    events = await _drain(session, 600)

    assert isinstance(events[0], SpeechStarted)
    assert isinstance(events[-1], UtteranceEnd)
    finals = [e for e in events if isinstance(e, FinalTranscript)]
    assert len(finals) == 1
    assert finals[0].text == "ocho mil quinientos"
    assert (finals[0].offset_ms, finals[0].end_offset_ms) == (100, 500)


async def test_partials_are_progressive_prefixes() -> None:
    session = FakeSttSession([ScriptedUtterance("ocho mil quinientos", 100, 500)])
    events = await _drain(session, 600)

    partials = [e.text for e in events if isinstance(e, PartialTranscript)]
    assert partials == ["ocho", "ocho mil", "ocho mil quinientos"]


async def test_nothing_is_emitted_before_its_audio_arrives() -> None:
    """The fake runs on the audio clock, so a test cannot accidentally see the future."""
    session = FakeSttSession([ScriptedUtterance("hola", 1000, 1200)])
    events = await _drain(session, 500)
    assert events == []


async def test_a_pause_mid_sentence_is_not_the_agent_s_turn() -> None:
    """is_endpoint=False: words are settled, the speaker is not finished. Ugly case #3."""
    session = FakeSttSession([ScriptedUtterance("déjame ver", 100, 300, is_endpoint=False)])
    events = await _drain(session, 400)

    assert any(isinstance(e, FinalTranscript) for e in events)
    assert not any(isinstance(e, UtteranceEnd) for e in events), (
        "a pause must not release the agent"
    )


async def test_two_utterances_stay_in_order() -> None:
    session = FakeSttSession(
        [ScriptedUtterance("son ocho mil", 100, 400), ScriptedUtterance("no, nueve mil", 800, 1100)]
    )
    events = await _drain(session, 1200)

    finals = [e.text for e in events if isinstance(e, FinalTranscript)]
    assert finals == ["son ocho mil", "no, nueve mil"]
    # Ugly case #2: the second statement is a new event, never an edit of the first.
    assert len([e for e in events if isinstance(e, SpeechStarted)]) == 2


async def test_provider_hands_out_independent_sessions() -> None:
    provider = FakeStt([ScriptedUtterance("hola", 100, 200)])
    first, second = await provider.connect(), await provider.connect()
    assert first is not second

    assert await _drain(first, 300) != []
    assert await _drain(second, 300) != [], "a second call must not replay a drained script"

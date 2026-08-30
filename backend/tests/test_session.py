"""The turn loop. Deterministic — no wall-clock races, no network, no PSTN.

Only two tests, but they cover the failure that is both silent and expensive: an agent
that keeps talking over the person interrupting it, and that afterwards believes it said
things the other side never heard.
"""

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from agents import TResponseInputItem

from app.agent import RECOVERY_LINE
from app.domain.models import Speaker, TranscriptTrack
from app.voice.llm import Thinker
from app.voice.session import FinalTranscriptSink, VoiceSession
from app.voice.simline import SimLine
from app.voice.stt.fake import FakeStt, ScriptedUtterance
from app.voice.tts.fake import FakeTts
from app.voice.vad import VadSettings

FIRST_CLAUSE = "Let me confirm that detail."


class StallingThinker:
    """Says one clause, then never finishes. Only a cancel can end this turn."""

    async def reply(self, history: Sequence[TResponseInputItem]) -> AsyncIterator[str]:
        yield FIRST_CLAUSE
        await asyncio.Event().wait()
        yield "this must never be heard"


class OneLinerThinker:
    async def reply(self, history: Sequence[TResponseInputItem]) -> AsyncIterator[str]:
        yield "Understood."


def _session(thinker: Thinker, script: list[ScriptedUtterance]) -> VoiceSession:
    return VoiceSession(
        stt=FakeStt(script),
        tts=FakeTts(),
        reasoner=thinker,
        vad=VadSettings(barge_in_min_ms=120),
        greeting="Hello.",
        latency_evidence="SIMULATED_TEST",
    )


async def test_barge_in_cancels_the_reply_and_keeps_only_what_was_said() -> None:
    script = [
        ScriptedUtterance("hello what do you need", 100, 300),
        ScriptedUtterance("no wait", 500, 900),  # starts while the agent is talking
    ]
    line = SimLine(script, tail_ms=400, pace_s=0)
    session = _session(StallingThinker(), script)

    await session.run(line, line)

    assistant = [m["content"] for m in session.history if m.get("role") == "assistant"]
    interrupted = [text for text in assistant if "[interrupted]" in str(text)]

    assert interrupted, "an interrupted turn must be recorded as interrupted"
    assert FIRST_CLAUSE in str(interrupted[0])
    # The clause after the stall was never handed to the synthesizer, so the agent must
    # not believe it said it. This is what keeps the transcript honest.
    assert not any("must never be heard" in str(text) for text in assistant)
    assert line.clears >= 1, "barge-in must drop the audio already queued on the line"


async def test_a_clean_turn_records_both_sides() -> None:
    script = [ScriptedUtterance("yes we serve that lane", 100, 400)]
    line = SimLine(script, tail_ms=400, pace_s=0)
    session = _session(OneLinerThinker(), script)

    await session.run(line, line)

    assert [m.get("role") for m in session.history] == ["assistant", "user", "assistant"]
    assert session.history[1]["content"] == "yes we serve that lane"
    assert len(session.latency_samples) == 1
    latency = session.latency_samples[0]
    assert latency.evidence == "SIMULATED_TEST"
    assert latency.model_first_chunk_ms is not None
    assert latency.tts_first_audio_ms is not None
    assert latency.end_to_end_first_audio_ms is not None
    assert latency.spoken_words == 1
    assert latency.estimated_spoken_ms == 400
    assert not latency.ordinary_turn_over_budget
    assert not latency.interrupted


class ExplodingThinker:
    """The model fails mid-turn — a bad key, a timeout, a 500."""

    async def reply(self, history: Sequence[TResponseInputItem]) -> AsyncIterator[str]:
        raise RuntimeError("the model fell over")
        yield ""  # unreachable, but it is what makes this an async generator


async def test_a_model_failure_does_not_leave_the_line_silent() -> None:
    """Dead air reads as a dropped call. The turn must come back to the human."""
    script = [ScriptedUtterance("give me a price", 100, 400)]
    line = SimLine(script, tail_ms=400, pace_s=0)
    session = _session(ExplodingThinker(), script)

    await session.run(line, line)

    assistant = [str(m["content"]) for m in session.history if m.get("role") == "assistant"]
    assert RECOVERY_LINE in assistant, "a failed turn must still say something"


async def test_interrupted_turn_records_only_audio_that_started() -> None:
    script = [
        ScriptedUtterance("answer me", 100, 300),
        ScriptedUtterance("I am interrupting", 500, 900),
    ]
    line = SimLine(script, tail_ms=300, pace_s=0)
    session = _session(StallingThinker(), script)

    await session.run(line, line)

    interrupted = [sample for sample in session.latency_samples if sample.interrupted]
    assert interrupted
    assert interrupted[0].end_to_end_first_audio_ms is not None


@dataclass(frozen=True, slots=True)
class Recorded:
    track: str
    speaker: str
    sequence_number: int
    audio_offset_ms: int
    text: str
    interrupted: bool


def _recording_sink(into: list[Recorded]) -> FinalTranscriptSink:
    async def sink(
        call_sid: str,
        track: TranscriptTrack,
        speaker: Speaker,
        *,
        sequence_number: int,
        audio_offset_ms: int,
        text: str,
        interrupted: bool = False,
    ) -> None:
        into.append(
            Recorded(str(track), str(speaker), sequence_number, audio_offset_ms, text, interrupted)
        )

    return sink


async def _run_one_turn(recorded: list[Recorded]) -> None:
    script = [ScriptedUtterance("nueve mil pesos", 100, 400)]
    session = VoiceSession(
        stt=FakeStt(script),
        tts=FakeTts(),
        reasoner=OneLinerThinker(),
        vad=VadSettings(barge_in_min_ms=120),
        greeting="Buenas.",
        on_final_transcript=_recording_sink(recorded),
    )
    source = SimLine(script, tail_ms=400, pace_s=0)
    sink_line = SimLine(script, tail_ms=400, pace_s=0)
    await session.run(source, sink_line)


async def test_final_transcripts_include_both_call_sides_for_post_call_evidence() -> None:
    recorded: list[Recorded] = []
    await _run_one_turn(recorded)

    assert any(
        r.track == "inbound"
        and r.speaker == "caller"
        and r.audio_offset_ms == 100
        and r.text == "nueve mil pesos"
        for r in recorded
    )
    assert any(r.track == "outbound" and r.speaker == "agent" for r in recorded)
    # The counter belongs to the session, not to a dict in the app factory: one call,
    # one sequence, starting at 1 and never re-seeded from a database read.
    assert [r.sequence_number for r in recorded] == list(range(1, len(recorded) + 1))


async def test_agent_turn_is_anchored_after_the_utterance_it_answers() -> None:
    """The challenge requires a commitment to link to the moment it was agreed.

    The agent's own line used to be persisted at the counterparty's UtteranceEnd offset —
    an instant *before* the agent had said anything at all, and one instant for a whole
    multi-clause reply. It must now sit at the transport's stream position at the moment
    the reply's first audio went out.
    """
    recorded: list[Recorded] = []
    await _run_one_turn(recorded)

    utterance_end_ms = 400  # ScriptedUtterance("nueve mil pesos", 100, 400)
    agent = [r for r in recorded if r.speaker == "agent"]
    assert agent, "the agent turn must be recorded"
    assert agent[0].audio_offset_ms > utterance_end_ms, (
        f"agent turn anchored at {agent[0].audio_offset_ms} ms, "
        f"which is not after the utterance it answers ({utterance_end_ms} ms)"
    )
    assert not agent[0].interrupted

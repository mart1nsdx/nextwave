"""The turn loop. Deterministic — no wall-clock races, no network, no PSTN.

Only two tests, but they cover the failure that is both silent and expensive: an agent
that keeps talking over the person interrupting it, and that afterwards believes it said
things the other side never heard.
"""

import asyncio
from collections.abc import AsyncIterator, Sequence

from agents import TResponseInputItem

from app.agent import RECOVERY_LINE
from app.voice.llm import Thinker
from app.voice.session import VoiceSession
from app.voice.simline import SimLine
from app.voice.stt.fake import FakeStt, ScriptedUtterance
from app.voice.tts.fake import FakeTts
from app.voice.vad import VadSettings

FIRST_CLAUSE = "Permítame confirmo el dato."


class StallingThinker:
    """Says one clause, then never finishes. Only a cancel can end this turn."""

    async def reply(self, history: Sequence[TResponseInputItem]) -> AsyncIterator[str]:
        yield FIRST_CLAUSE
        await asyncio.Event().wait()
        yield "esto no debería oírse nunca"


class OneLinerThinker:
    async def reply(self, history: Sequence[TResponseInputItem]) -> AsyncIterator[str]:
        yield "Entendido."


def _session(thinker: Thinker, script: list[ScriptedUtterance]) -> VoiceSession:
    return VoiceSession(
        stt=FakeStt(script),
        tts=FakeTts(),
        reasoner=thinker,
        vad=VadSettings(barge_in_min_ms=120),
        greeting="Buenas.",
    )


async def test_barge_in_cancels_the_reply_and_keeps_only_what_was_said() -> None:
    script = [
        ScriptedUtterance("bueno qué necesita", 100, 300),
        ScriptedUtterance("no espéreme", 500, 900),  # starts while the agent is talking
    ]
    line = SimLine(script, tail_ms=400, pace_s=0)
    session = _session(StallingThinker(), script)

    await session.run(line, line)

    assistant = [m["content"] for m in session.history if m.get("role") == "assistant"]
    interrupted = [text for text in assistant if "[interrumpido]" in str(text)]

    assert interrupted, "an interrupted turn must be recorded as interrupted"
    assert FIRST_CLAUSE in str(interrupted[0])
    # The clause after the stall was never handed to the synthesizer, so the agent must
    # not believe it said it. This is what keeps the transcript honest.
    assert not any("no debería oírse" in str(text) for text in assistant)
    assert line.clears >= 1, "barge-in must drop the audio already queued on the line"


async def test_a_clean_turn_records_both_sides() -> None:
    script = [ScriptedUtterance("sí manejamos esa ruta", 100, 400)]
    line = SimLine(script, tail_ms=400, pace_s=0)
    session = _session(OneLinerThinker(), script)

    await session.run(line, line)

    assert [m.get("role") for m in session.history] == ["assistant", "user", "assistant"]
    assert session.history[1]["content"] == "sí manejamos esa ruta"


class ExplodingThinker:
    """The model fails mid-turn — a bad key, a timeout, a 500."""

    async def reply(self, history: Sequence[TResponseInputItem]) -> AsyncIterator[str]:
        raise RuntimeError("the model fell over")
        yield ""  # unreachable, but it is what makes this an async generator


async def test_a_model_failure_does_not_leave_the_line_silent() -> None:
    """Dead air reads as a dropped call. The turn must come back to the human."""
    script = [ScriptedUtterance("me da un precio", 100, 400)]
    line = SimLine(script, tail_ms=400, pace_s=0)
    session = _session(ExplodingThinker(), script)

    await session.run(line, line)

    assistant = [str(m["content"]) for m in session.history if m.get("role") == "assistant"]
    assert RECOVERY_LINE in assistant, "a failed turn must still say something"


async def test_final_transcripts_include_both_call_sides_for_post_call_evidence() -> None:
    script = [ScriptedUtterance("nueve mil pesos", 100, 400)]
    recorded: list[tuple[str, str, int, str]] = []

    async def sink(call_id: str, track: object, speaker: object, offset: int, text: str) -> None:
        recorded.append((str(track), str(speaker), offset, text))

    session = VoiceSession(
        stt=FakeStt(script),
        tts=FakeTts(),
        reasoner=OneLinerThinker(),
        vad=VadSettings(barge_in_min_ms=120),
        greeting="Buenas.",
        on_final_transcript=sink,
    )
    source = SimLine(script, tail_ms=400, pace_s=0)
    sink_line = SimLine(script, tail_ms=400, pace_s=0)
    await session.run(source, sink_line)

    assert ("inbound", "caller", 100, "nueve mil pesos") in recorded
    assert any(track == "outbound" and speaker == "agent" for track, speaker, _, _ in recorded)

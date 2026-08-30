"""Runs the agent and turns its token stream into speakable chunks.

Two jobs. First, streaming: waiting for a complete answer before speaking adds the whole
generation time to the silence after the counterparty stops talking, which on a phone
call reads as the line having died. Second, chunking: the synthesizer wants clauses, not
tokens — one Speak per token is wasteful and gives flat, choppy prosody.

Cancellation matters here. Barge-in cancels this mid-generation, so nothing may buffer
state that a cancelled run would leave inconsistent.
"""

from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol

from agents import Agent, Runner, TResponseInputItem
from openai.types.responses import ResponseTextDeltaEvent

# Break on clause endings, not just sentence endings: a comma after twelve words is a
# natural place to start speaking, and it buys latency at the start of a turn.
_CLAUSE_ENDINGS = ".?!…:;\n"
_SOFT_ENDINGS = ",—"
_MIN_CHUNK = 12
_SOFT_MIN_CHUNK = 40
_MAX_CHUNK = 96


class Thinker(Protocol):
    """What the turn loop needs from a brain: history in, speakable chunks out.

    A Protocol so sim_call and tests can drive the whole conversation with a scripted
    reply — no API key, no cost, no non-determinism — while the real path is unchanged.
    """

    def reply(self, history: Sequence[TResponseInputItem]) -> AsyncIterator[str]: ...


class Reasoner:
    def __init__(self, agent: Agent) -> None:
        self._agent = agent

    async def reply(self, history: Sequence[TResponseInputItem]) -> AsyncIterator[str]:
        """Yield speakable chunks as the model produces them."""
        buffer = ""
        result = Runner.run_streamed(self._agent, input=list(history))

        async for event in result.stream_events():
            if event.type != "raw_response_event":
                continue
            data: Any = event.data
            if not isinstance(data, ResponseTextDeltaEvent):
                continue

            buffer += data.delta
            while (chunk := _take_chunk(buffer)) is not None:
                emitted, buffer = chunk
                yield emitted

        if buffer.strip():
            yield buffer.strip()


def _take_chunk(buffer: str) -> tuple[str, str] | None:
    """Split off a speakable clause, or None if the buffer is not ready yet."""
    for index, character in enumerate(buffer):
        length = index + 1
        if character in _CLAUSE_ENDINGS and length >= _MIN_CHUNK:
            return buffer[:length].strip(), buffer[length:]
        if character in _SOFT_ENDINGS and length >= _SOFT_MIN_CHUNK:
            return buffer[:length].strip(), buffer[length:]
    if len(buffer) >= _MAX_CHUNK:
        # No punctuation in sight. Break at the last space so a word is not cut in half.
        cut = buffer.rfind(" ", 0, _MAX_CHUNK)
        cut = cut if cut > 0 else _MAX_CHUNK
        return buffer[:cut].strip(), buffer[cut:]
    return None

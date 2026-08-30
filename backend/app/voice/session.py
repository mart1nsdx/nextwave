"""The turn loop: hear, think, speak, and shut up when interrupted.

Four things run concurrently for the life of a call:

    _pump    frames from the phone -> recognizer, and the local barge-in gate
    _listen  recognizer events -> when the counterparty finishes, start a reply
    _play    synthesizer audio -> back out to the phone
    _greet   the opening line

Splitting them is what makes barge-in possible at all: the frame pump keeps running
while the agent is talking, so an interruption is noticed in about one frame rather than
after the current turn finishes.
"""

import asyncio
import contextlib
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from enum import Enum, auto
from typing import Protocol

import structlog
from agents import TResponseInputItem

from app.agent import GREETING, RECOVERY_LINE, build_agent
from app.config import Settings
from app.domain.models import HandoffReason, Speaker, TranscriptTrack
from app.tools import detected_handoff_reason
from app.tools.conversation_guard import ConversationGuard, build_demo_guard

from .events import FinalTranscript, SpeechStarted, UtteranceEnd
from .frames import AudioSink, AudioSource
from .latency import ActiveTurnLatency, TurnLatency
from .llm import Reasoner, Thinker
from .stt import SttProvider, SttSession, make_stt
from .tts import TtsProvider, TtsSession, make_tts
from .vad import EnergyVad, VadSettings

log = structlog.get_logger(__name__)

HandoffSink = Callable[[str, HandoffReason, int, str], Awaitable[bool]]


class FinalTranscriptSink(Protocol):
    """What the session calls once a segment is settled. Wired to the evidence ledger.

    ``sequence_number`` is supplied by the session because a call is the only scope in
    which the count is meaningful, and because the previous owner — a dict in the app
    factory keyed by CallSid — leaked for the process lifetime and could hand the same
    number to two different segments.
    """

    async def __call__(
        self,
        call_sid: str,
        track: TranscriptTrack,
        speaker: Speaker,
        *,
        sequence_number: int,
        audio_offset_ms: int,
        text: str,
        interrupted: bool = False,
    ) -> None: ...


class Turn(Enum):
    LISTENING = auto()
    SPEAKING = auto()


class VoiceSession:
    """One conversation. Not reusable across calls — build a new one per connection."""

    def __init__(
        self,
        stt: SttProvider,
        tts: TtsProvider,
        reasoner: Thinker,
        vad: VadSettings,
        greeting: str,
        clock: Callable[[], float] = time.perf_counter,
        latency_evidence: str = "LIVE",
        guard: ConversationGuard | None = None,
        on_final_transcript: FinalTranscriptSink | None = None,
        on_handoff: HandoffSink | None = None,
    ) -> None:
        self._stt = stt
        self._tts = tts
        self._reasoner = reasoner
        self._vad_settings = vad
        self._greeting = greeting
        self._clock = clock
        self._latency_evidence = latency_evidence
        self._guard = guard
        self._on_final_transcript = on_final_transcript
        self._on_handoff = on_handoff

        self._turn = Turn.LISTENING
        self._history: list[TResponseInputItem] = []
        self._heard: list[str] = []
        self._reply: asyncio.Task[None] | None = None
        self._sink: AudioSink | None = None
        self._source: AudioSource | None = None
        self._voice: TtsSession | None = None
        self._latencies: list[TurnLatency] = []
        self._active_latency: ActiveTurnLatency | None = None
        self._audio_wall: deque[tuple[int, float]] = deque(maxlen=3000)
        self._log = log
        self._call_id = ""
        self._handoff_requested = False
        self._sequence = 0
        self._turn_anchor_ms: int | None = None

    @property
    def history(self) -> list[TResponseInputItem]:
        """The conversation so far. The raw material for the call brief."""
        return list(self._history)

    @property
    def latency_samples(self) -> tuple[TurnLatency, ...]:
        return tuple(self._latencies)

    async def run(self, source: AudioSource, sink: AudioSink) -> None:
        # Bound once, so every line this call produces can be filtered out of the three
        # conversations running in parallel.
        self._log = log.bind(call_id=source.call_id)
        self._call_id = source.call_id
        stt = await self._stt.connect()
        voice = await self._tts.connect()
        self._source, self._sink, self._voice = source, sink, voice
        self._vad = EnergyVad(self._vad_settings)

        async with asyncio.TaskGroup() as group:
            group.create_task(self._play(voice, sink))
            group.create_task(self._listen(stt))
            group.create_task(self._greet(voice))
            group.create_task(self._pump(source, stt, voice))

    # --- the four concurrent jobs -------------------------------------------------

    async def _pump(self, source: AudioSource, stt: SttSession, voice: TtsSession) -> None:
        """Feed the recognizer, and watch locally for an interruption."""
        async for frame in source.frames():
            self._audio_wall.append((frame.offset_ms, self._clock()))
            await stt.send(frame)
            if self._vad.feed(frame.payload) and self._turn is Turn.SPEAKING:
                await self._barge_in(frame.offset_ms)

        # The call ended. Everything else unwinds from here.
        await self._cancel_reply()
        await stt.close()
        await voice.close()

    async def _listen(self, stt: SttSession) -> None:
        async for event in stt.events():
            if isinstance(event, FinalTranscript):
                # Settled words. They may still be mid-sentence, so they accumulate;
                # only UtteranceEnd means the counterparty actually stopped.
                self._heard.append(event.text)
                if self._on_final_transcript is not None:
                    # The transport learns CallSid in Twilio's start event, which may
                    # arrive just after this session was created.
                    if self._source is not None:
                        self._call_id = self._source.call_id
                    await self._persist(
                        TranscriptTrack.INBOUND,
                        Speaker.CALLER,
                        event.offset_ms,
                        event.text,
                    )
                reason = detected_handoff_reason(event.text)
                if (
                    reason is not None
                    and not self._handoff_requested
                    and self._on_handoff is not None
                ):
                    self._handoff_requested = True
                    await self._barge_in(event.offset_ms)
                    started = await self._on_handoff(
                        self._call_id,
                        reason,
                        event.offset_ms,
                        "deterministic transcript trigger",
                    )
                    if not started:
                        self._handoff_requested = False
                        self._heard.clear()
                        await self._speak(
                            "I could not connect a colleague right now. "
                            "My team will return your call."
                        )
                        await self._flush()
            elif isinstance(event, UtteranceEnd):
                if self._heard and not self._handoff_requested:
                    self._reply = asyncio.create_task(self._respond(event.offset_ms))
                    # Without this, a crash inside the turn is only ever reported by
                    # asyncio at shutdown as "Task exception was never retrieved", long
                    # after the call went quiet.
                    self._reply.add_done_callback(self._note_reply_outcome)
            elif isinstance(event, SpeechStarted):
                self._log.debug("speech_started", offset_ms=event.offset_ms)

    async def _play(self, voice: TtsSession, sink: AudioSink) -> None:
        async for chunk in voice.audio():
            if self._turn_anchor_ms is None and self._source is not None:
                # The transport's presentation timestamp at the instant this turn's first
                # audio goes on the wire. Read here rather than in _respond because this
                # is the moment the counterparty could first have heard anything.
                self._turn_anchor_ms = self._source.last_offset_ms
            await sink.send_audio(chunk)
            active = self._active_latency
            if (
                active is not None
                and active.model_first_chunk_at is not None
                and active.tts_first_audio_at is None
            ):
                active.tts_first_audio_at = self._clock()
                self._log.info(
                    "latency_first_audio",
                    turn=active.turn,
                    evidence=active.evidence,
                    end_to_end_ms=round((active.tts_first_audio_at - active.started_at) * 1000, 1),
                )
                if active.response_complete_at is not None:
                    self._finalize_latency(interrupted=False)

    async def _greet(self, voice: TtsSession) -> None:
        self._turn = Turn.SPEAKING
        self._history.append({"role": "assistant", "content": self._greeting})
        await voice.speak(self._greeting)
        await voice.flush()

    # --- turn taking ---------------------------------------------------------------

    async def _respond(self, offset_ms: int) -> None:
        heard = " ".join(self._heard).strip()
        self._heard.clear()
        if not heard:
            return

        started_at = self._clock()
        audio_ended_at = self._wall_at_or_before(offset_ms)
        self._active_latency = ActiveTurnLatency(
            turn=len(self._latencies) + 1,
            evidence=self._latency_evidence,
            response_source="MODEL",
            utterance_end_offset_ms=offset_ms,
            started_at=started_at,
            stt_endpoint_ms=round(max(0.0, (started_at - audio_ended_at) * 1000), 1),
        )
        self._history.append({"role": "user", "content": heard})
        self._log.info("heard", text=heard, offset_ms=offset_ms)

        # Stays SPEAKING after generation finishes, because Twilio is still playing the
        # audio out. Resetting here would make the agent deaf to an interruption during
        # the very stretch where interruptions actually happen.
        self._turn = Turn.SPEAKING
        # A fresh anchor per turn: _play fills it the moment this reply's first audio
        # reaches the sink.
        self._turn_anchor_ms = None
        said = ""
        interrupted = False
        try:
            directive = (
                self._guard.input_directive(
                    heard,
                    call_id=self._call_id,
                    offset_ms=offset_ms,
                )
                if self._guard is not None
                else None
            )
            if directive is not None and self._active_latency is not None:
                self._active_latency.response_source = "POLICY_FAST_PATH"
            chunks = _one_chunk(directive) if directive else self._reasoner.reply(self._history)
            async for raw_chunk in chunks:
                chunk, blocked = (
                    self._guard.filter_model_chunk(raw_chunk)
                    if self._guard is not None and directive is None
                    else (raw_chunk, False)
                )
                active = self._active_latency
                if active is not None and active.model_first_chunk_at is None:
                    active.model_first_chunk_at = self._clock()
                    self._log.info(
                        "latency_first_model_chunk",
                        turn=active.turn,
                        evidence=active.evidence,
                        model_first_chunk_ms=round(
                            (active.model_first_chunk_at - active.started_at) * 1000, 1
                        ),
                    )
                said = f"{said} {chunk}".strip()
                await self._speak(chunk)
                if blocked:
                    break
            await self._flush()
            self._history.append({"role": "assistant", "content": said})
            self._log.info("said", text=said)
            if self._active_latency is not None:
                self._active_latency.spoken_text = said
            self._finish_latency(interrupted=False)
        except asyncio.CancelledError:
            # Record only what was handed to the synthesizer. The counterparty may have
            # heard less — playback was still in flight — but never more, so the agent
            # can never later claim it said something the other side never got.
            interrupted = True
            if said:
                self._history.append({"role": "assistant", "content": f"{said} [interrupted]"})
            if self._active_latency is not None:
                self._active_latency.spoken_text = said
            self._log.info("reply_interrupted", spoken_chars=len(said))
            self._finish_latency(interrupted=True)
            raise
        except Exception:
            # The model failed. Dead air reads as a dropped call and the counterparty
            # hangs up, so say something and hand the turn back. RECOVERY_LINE states
            # nothing and confirms nothing: a technical failure must never come out of
            # the agent's mouth as agreement (invariant #6).
            self._log.exception("reply_failed", spoken_chars=len(said))
            self._history.append({"role": "assistant", "content": RECOVERY_LINE})
            await self._speak(RECOVERY_LINE)
            await self._flush()
            self._finish_latency(interrupted=False)
        finally:
            # A bidirectional Twilio stream exposes only the caller's incoming track, so
            # the agent's own line is written here or nowhere. It lives in a `finally`
            # because the turn a judge is most likely to create is the one that gets cut
            # off, and a barge-in reply that reached the phone but never the ledger is
            # evidence that silently does not exist. `said` is still only what was handed
            # to the synthesizer — never more.
            await self._persist(
                TranscriptTrack.OUTBOUND,
                Speaker.AGENT,
                self._agent_turn_offset_ms(offset_ms),
                said,
                interrupted=interrupted,
            )

    async def _persist(
        self,
        track: TranscriptTrack,
        speaker: Speaker,
        audio_offset_ms: int,
        text: str,
        *,
        interrupted: bool = False,
    ) -> None:
        """Hand one settled segment to the ledger, numbered within this call.

        One call, one session, one counter — no dict keyed by CallSid outliving the call
        it described, and no seeding read that two events can race across an await.
        """
        if self._on_final_transcript is None or not text:
            return
        self._sequence += 1
        await self._on_final_transcript(
            self._call_id,
            track,
            speaker,
            sequence_number=self._sequence,
            audio_offset_ms=audio_offset_ms,
            text=text,
            interrupted=interrupted,
        )

    def _agent_turn_offset_ms(self, utterance_end_ms: int) -> int:
        """When the agent spoke, not when the counterparty stopped.

        UtteranceEnd's offset is an instant *before* this reply existed, and a single
        instant for a whole multi-clause answer. Anchoring an agent turn there points a
        commitment at a moment when nothing had been agreed (AGENTS.md invariant #3).
        """
        if self._turn_anchor_ms is not None:
            return self._turn_anchor_ms
        # Nothing reached the sink for this turn. The live stream position is still an
        # offset the transport observed, never one computed here.
        if self._source is not None:
            return max(self._source.last_offset_ms, utterance_end_ms)
        return utterance_end_ms

    async def _barge_in(self, offset_ms: int) -> None:
        """Stop talking, now. Three cuts, because audio is buffered in three places."""
        self._log.info("barge_in", offset_ms=offset_ms)
        self._turn = Turn.LISTENING
        cut_started = self._clock()
        if self._sink is not None:
            await self._sink.clear()  # what the phone network already has queued
        if self._voice is not None:
            await self._voice.clear()  # what the synthesizer is still generating
        await self._cancel_reply()  # and the model still producing text
        clear_ms = round((self._clock() - cut_started) * 1000, 1)
        self._log.info(
            "barge_in_latency",
            clear_ms=clear_ms,
            estimated_total_ms=round(self._vad_settings.barge_in_min_ms + clear_ms, 1),
            evidence=self._latency_evidence,
        )

    def _note_reply_outcome(self, task: "asyncio.Task[None]") -> None:
        """Never let a turn fail silently."""
        if not task.cancelled() and task.exception() is not None:
            self._log.error("reply_task_failed", error=repr(task.exception()))

    async def _cancel_reply(self) -> None:
        task, self._reply = self._reply, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _speak(self, text: str) -> None:
        if self._voice is not None:
            await self._voice.speak(text)
            # Some test/local providers enqueue synchronously. Yield once so the playback
            # task can observe the first frame before a fast response is marked complete.
            await asyncio.sleep(0)

    async def _flush(self) -> None:
        if self._voice is not None:
            await self._voice.flush()

    def _wall_at_or_before(self, offset_ms: int) -> float:
        for frame_offset, observed_at in reversed(self._audio_wall):
            if frame_offset <= offset_ms:
                return observed_at
        return self._clock()

    def _finish_latency(self, *, interrupted: bool) -> None:
        active = self._active_latency
        if active is None:
            return
        active.response_complete_at = self._clock()
        if (
            not interrupted
            and active.model_first_chunk_at is not None
            and active.tts_first_audio_at is None
        ):
            return
        self._finalize_latency(interrupted=interrupted)

    def _finalize_latency(self, *, interrupted: bool) -> None:
        active, self._active_latency = self._active_latency, None
        if active is None:
            return
        sample = active.finish(self._clock(), interrupted=interrupted)
        self._latencies.append(sample)
        self._log.info(
            "turn_latency",
            **{
                "turn": sample.turn,
                "evidence": sample.evidence,
                "response_source": sample.response_source,
                "stt_endpoint_ms": sample.stt_endpoint_ms,
                "model_first_chunk_ms": sample.model_first_chunk_ms,
                "tts_first_audio_ms": sample.tts_first_audio_ms,
                "end_to_end_first_audio_ms": sample.end_to_end_first_audio_ms,
                "response_complete_ms": sample.response_complete_ms,
                "spoken_words": sample.spoken_words,
                "estimated_spoken_ms": sample.estimated_spoken_ms,
                "ordinary_turn_over_budget": sample.ordinary_turn_over_budget,
                "interrupted": sample.interrupted,
            },
        )


def build_session(
    settings: Settings,
    on_final_transcript: FinalTranscriptSink | None = None,
    on_handoff: HandoffSink | None = None,
) -> VoiceSession:
    """Assemble a conversation from configuration. Called once per call."""
    return VoiceSession(
        stt=make_stt(settings),
        tts=make_tts(settings),
        reasoner=Reasoner(
            build_agent(
                settings.openai_agent_model,
                settings.openai_api_key,
                reasoning_effort=settings.openai_reasoning_effort,
                max_output_tokens=settings.openai_max_output_tokens,
            )
        ),
        vad=VadSettings.from_settings(settings),
        greeting=GREETING,
        latency_evidence="LIVE_PSTN",
        guard=build_demo_guard(),
        on_final_transcript=on_final_transcript,
        on_handoff=on_handoff,
    )


async def _one_chunk(text: str) -> AsyncIterator[str]:
    yield text

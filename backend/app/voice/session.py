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
from collections.abc import Callable
from enum import Enum, auto

import structlog
from agents import TResponseInputItem

from app.agent import GREETING, RECOVERY_LINE, build_agent
from app.config import Settings

from .events import FinalTranscript, SpeechStarted, UtteranceEnd
from .frames import AudioSink, AudioSource
from .latency import ActiveTurnLatency, TurnLatency
from .llm import Reasoner, Thinker
from .stt import SttProvider, SttSession, make_stt
from .tts import TtsProvider, TtsSession, make_tts
from .vad import EnergyVad, VadSettings

log = structlog.get_logger(__name__)


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
    ) -> None:
        self._stt = stt
        self._tts = tts
        self._reasoner = reasoner
        self._vad_settings = vad
        self._greeting = greeting
        self._clock = clock
        self._latency_evidence = latency_evidence

        self._turn = Turn.LISTENING
        self._history: list[TResponseInputItem] = []
        self._heard: list[str] = []
        self._reply: asyncio.Task[None] | None = None
        self._sink: AudioSink | None = None
        self._voice: TtsSession | None = None
        self._latencies: list[TurnLatency] = []
        self._active_latency: ActiveTurnLatency | None = None
        self._audio_wall: deque[tuple[int, float]] = deque(maxlen=3000)
        self._log = log

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
        stt = await self._stt.connect()
        voice = await self._tts.connect()
        self._sink, self._voice = sink, voice
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
            elif isinstance(event, UtteranceEnd):
                if self._heard:
                    self._reply = asyncio.create_task(self._respond(event.offset_ms))
                    # Without this, a crash inside the turn is only ever reported by
                    # asyncio at shutdown as "Task exception was never retrieved", long
                    # after the call went quiet.
                    self._reply.add_done_callback(self._note_reply_outcome)
            elif isinstance(event, SpeechStarted):
                self._log.debug("speech_started", offset_ms=event.offset_ms)

    async def _play(self, voice: TtsSession, sink: AudioSink) -> None:
        async for chunk in voice.audio():
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
        said = ""
        try:
            async for chunk in self._reasoner.reply(self._history):
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
            if said:
                self._history.append({"role": "assistant", "content": f"{said} [interrumpido]"})
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


def build_session(settings: Settings) -> VoiceSession:
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
    )

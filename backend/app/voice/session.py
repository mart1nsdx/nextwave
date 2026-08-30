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
from collections.abc import Awaitable, Callable
from enum import Enum, auto

import structlog
from agents import TResponseInputItem

from app.agent import (
    CallContext,
    build_agent,
    build_greeting,
    build_system_prompt,
    recovery_line,
)
from app.config import Settings
from app.domain import CompanyProfile
from app.domain.models import HandoffReason, Speaker, TranscriptTrack
from app.tools import detected_handoff_reason

from .events import FinalTranscript, SpeechStarted, UtteranceEnd
from .frames import AudioSink, AudioSource
from .llm import Reasoner, Thinker
from .stt import SttProvider, SttSession, make_stt
from .tts import TtsProvider, TtsSession, make_tts
from .vad import EnergyVad, VadSettings

log = structlog.get_logger(__name__)

FinalTranscriptSink = Callable[[str, TranscriptTrack, Speaker, int, str], Awaitable[None]]
HandoffSink = Callable[[str, HandoffReason, int, str], Awaitable[bool]]


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
        recovery: str,
        on_final_transcript: FinalTranscriptSink | None = None,
        on_handoff: HandoffSink | None = None,
    ) -> None:
        self._stt = stt
        self._tts = tts
        self._reasoner = reasoner
        self._vad_settings = vad
        self._greeting = greeting
        self._recovery = recovery
        self._on_final_transcript = on_final_transcript
        self._on_handoff = on_handoff

        self._turn = Turn.LISTENING
        self._history: list[TResponseInputItem] = []
        self._heard: list[str] = []
        self._reply: asyncio.Task[None] | None = None
        self._sink: AudioSink | None = None
        self._source: AudioSource | None = None
        self._voice: TtsSession | None = None
        self._log = log
        self._call_id = ""
        self._handoff_requested = False

    @property
    def history(self) -> list[TResponseInputItem]:
        """The conversation so far. The raw material for the call brief."""
        return list(self._history)

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
                    await self._on_final_transcript(
                        self._call_id,
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
                            "No logramos conectar con una persona en este momento. "
                            "Tomaremos el recado para que el equipo le devuelva la llamada."
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
            await sink.send_audio(chunk)

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

        self._history.append({"role": "user", "content": heard})
        self._log.info("heard", text=heard, offset_ms=offset_ms)

        # Stays SPEAKING after generation finishes, because Twilio is still playing the
        # audio out. Resetting here would make the agent deaf to an interruption during
        # the very stretch where interruptions actually happen.
        self._turn = Turn.SPEAKING
        said = ""
        try:
            async for chunk in self._reasoner.reply(self._history):
                said = f"{said} {chunk}".strip()
                await self._speak(chunk)
            await self._flush()
            self._history.append({"role": "assistant", "content": said})
            if said and self._on_final_transcript is not None:
                # A bidirectional Twilio stream exposes only the caller's incoming
                # track. Record the generated reply separately, anchored to the turn
                # it answers, so the post-call brief can account for agent actions.
                await self._on_final_transcript(
                    self._call_id,
                    TranscriptTrack.OUTBOUND,
                    Speaker.AGENT,
                    offset_ms,
                    said,
                )
            self._log.info("said", text=said)
        except asyncio.CancelledError:
            # Record only what was handed to the synthesizer. The counterparty may have
            # heard less — playback was still in flight — but never more, so the agent
            # can never later claim it said something the other side never got.
            if said:
                self._history.append({"role": "assistant", "content": f"{said} [interrumpido]"})
            self._log.info("reply_interrupted", spoken_chars=len(said))
            raise
        except Exception:
            # The model failed. Dead air reads as a dropped call and the counterparty
            # hangs up, so say something and hand the turn back. RECOVERY_LINE states
            # nothing and confirms nothing: a technical failure must never come out of
            # the agent's mouth as agreement (invariant #6).
            self._log.exception("reply_failed", spoken_chars=len(said))
            self._history.append({"role": "assistant", "content": self._recovery})
            await self._speak(self._recovery)
            await self._flush()

    async def _barge_in(self, offset_ms: int) -> None:
        """Stop talking, now. Three cuts, because audio is buffered in three places."""
        self._log.info("barge_in", offset_ms=offset_ms)
        self._turn = Turn.LISTENING
        if self._sink is not None:
            await self._sink.clear()  # what the phone network already has queued
        if self._voice is not None:
            await self._voice.clear()  # what the synthesizer is still generating
        await self._cancel_reply()  # and the model still producing text

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

    async def _flush(self) -> None:
        if self._voice is not None:
            await self._voice.flush()


def build_session(
    settings: Settings,
    profile: CompanyProfile,
    context: CallContext,
    on_final_transcript: FinalTranscriptSink | None = None,
    on_handoff: HandoffSink | None = None,
) -> VoiceSession:
    """Assemble one conversation. Called once per call, after the phase is known.

    Every spoken constant is composed here from `profile` and `context` rather than read
    from a module: the greeting, the instructions and the recovery line all have to agree
    about who the agent works for and what this call is, and the only way to guarantee
    that is to derive them from the same two objects at the same moment.
    """
    return VoiceSession(
        stt=make_stt(settings),
        tts=make_tts(settings),
        reasoner=Reasoner(
            build_agent(
                settings.openai_agent_model,
                settings.openai_api_key,
                instructions=build_system_prompt(profile, context),
            )
        ),
        vad=VadSettings.from_settings(settings),
        greeting=build_greeting(profile, context),
        recovery=recovery_line(profile),
        on_final_transcript=on_final_transcript,
        on_handoff=on_handoff,
    )

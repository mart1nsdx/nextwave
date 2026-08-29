"""Deepgram streaming recognition, translated into voice/events.py types.

Hand-rolled on `websockets` rather than the Deepgram SDK: the SDK has had breaking
changes across major versions, this is about sixty lines, and we need direct control of
the socket anyway. Swapping it for an SDK-backed adapter later means writing another
class behind SttSession and changing STT_PROVIDER.

Audio goes in as mu-law 8 kHz — the same bytes Twilio delivered, unmodified.
"""

import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import structlog
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from ..events import FinalTranscript, PartialTranscript, SpeechStarted, SttEvent, UtteranceEnd
from ..frames import InboundFrame
from . import SttSession

log = structlog.get_logger(__name__)

LISTEN_URL = "wss://api.deepgram.com/v1/listen"


class DeepgramSttSession:
    def __init__(self, socket: ClientConnection) -> None:
        self._socket = socket
        # Deepgram times everything from the first byte *it* received, which is not
        # necessarily the start of the call — a mid-call reconnect would restart its
        # clock. Anchoring to the first frame we sent keeps offsets in call time.
        self._origin_ms: int | None = None

    async def send(self, frame: InboundFrame) -> None:
        if self._origin_ms is None:
            self._origin_ms = frame.offset_ms
        try:
            await self._socket.send(frame.payload)
        except ConnectionClosed:
            pass

    async def events(self) -> AsyncIterator[SttEvent]:
        try:
            async for raw in self._socket:
                if isinstance(raw, bytes):
                    continue
                event = self._translate(json.loads(raw))
                if event is not None:
                    yield event
        except ConnectionClosed:
            return

    async def close(self) -> None:
        try:
            await self._socket.send(json.dumps({"type": "CloseStream"}))
        except ConnectionClosed:
            pass
        await self._socket.close()

    def _at(self, seconds: float) -> int:
        return (self._origin_ms or 0) + int(seconds * 1000)

    def _translate(self, message: dict[str, Any]) -> SttEvent | None:
        kind = message.get("type")

        if kind == "Results":
            alternatives = message.get("channel", {}).get("alternatives", [])
            text = alternatives[0].get("transcript", "").strip() if alternatives else ""
            if not text:
                return None  # Deepgram emits empty results during silence
            start = float(message.get("start", 0.0))
            if message.get("is_final"):
                return FinalTranscript(
                    text=text,
                    offset_ms=self._at(start),
                    end_offset_ms=self._at(start + float(message.get("duration", 0.0))),
                    # speech_final is Deepgram's endpointer saying the turn ended. A
                    # final without it means settled words mid-sentence, not our turn.
                    is_endpoint=bool(message.get("speech_final")),
                )
            return PartialTranscript(text=text, offset_ms=self._at(start))

        if kind == "SpeechStarted":
            return SpeechStarted(offset_ms=self._at(float(message.get("timestamp", 0.0))))

        if kind == "UtteranceEnd":
            return UtteranceEnd(offset_ms=self._at(float(message.get("last_word_end", 0.0))))

        return None  # Metadata, Warning, and anything Deepgram adds later


class DeepgramStt:
    def __init__(
        self,
        api_key: str,
        model: str,
        language: str,
        endpointing_ms: int,
        utterance_end_ms: int,
    ) -> None:
        if not api_key:
            raise ValueError("DEEPGRAM_API_KEY is empty — the agent would hear nothing.")
        self._api_key = api_key
        self._query = urlencode(
            {
                "model": model,
                "language": language,
                # The bytes Twilio sends, untouched. No resampling anywhere in the path.
                "encoding": "mulaw",
                "sample_rate": "8000",
                "channels": "1",
                "punctuate": "true",
                "smart_format": "true",
                # utterance_end_ms requires interim_results, and barge-in needs partials.
                "interim_results": "true",
                "endpointing": str(endpointing_ms),
                "utterance_end_ms": str(utterance_end_ms),
                "vad_events": "true",
            }
        )

    async def connect(self) -> DeepgramSttSession:
        socket = await connect(
            f"{LISTEN_URL}?{self._query}",
            additional_headers={"Authorization": f"Token {self._api_key}"},
        )
        log.info("stt_connected", provider="deepgram")
        return DeepgramSttSession(socket)


if TYPE_CHECKING:

    def _conforms(socket: ClientConnection) -> SttSession:
        return DeepgramSttSession(socket)

"""Streaming speech-to-text over Deepgram's live API.

Deepgram is the STT vendor: it accepts Twilio's G.711 mu-law 8 kHz frames directly (no
transcode) and returns word-level timestamps, which become the audio offsets a commitment
links back to (AGENTS.md invariant #3).

  - connect: wss://api.deepgram.com/v1/listen?encoding=mulaw&sample_rate=8000&channels=1&...
  - header:  Authorization: Token <DEEPGRAM_API_KEY>
  - send:    raw binary audio frames (not base64, not JSON)
  - receive: {"type":"Results","start":<s>,"is_final":<bool>,
              "channel":{"alternatives":[{"transcript":"..."}]}}
  - keepalive: {"type":"KeepAlive"} every few seconds when no audio flows
  - close:   {"type":"CloseStream"}

One instance drives one audio track of one call. telephony/ demultiplexes Twilio's
inbound/outbound tracks and owns a transcriber per track. Persistence is the injected
``on_event`` sink — this module never imports repo/ or ledger/ (layering contract).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any
from urllib.parse import urlencode

from app.domain.models import Speaker, TranscriptEvent, TranscriptTrack, build_event_key
from app.domain.ports import TranscriptSink

logger = logging.getLogger("volta.realtime")

_DEEPGRAM_URL = "wss://api.deepgram.com/v1/listen"
_KEEPALIVE_SECONDS = 7.0


class RealtimeTranscriber:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        language: str,
        call_sid: str,
        track: TranscriptTrack,
        on_event: TranscriptSink,
        speaker: Speaker | None = None,
    ) -> None:
        if not api_key:
            raise RuntimeError("DEEPGRAM_API_KEY must be set for transcription")
        self._api_key = api_key
        self._model = model
        self._language = language
        self._call_sid = call_sid
        self._track = track
        self._on_event = on_event
        self._speaker = speaker or (
            Speaker.CALLER if track is TranscriptTrack.INBOUND else Speaker.AGENT
        )

        self._ws: Any = None
        self._reader: asyncio.Task[None] | None = None
        self._keepalive: asyncio.Task[None] | None = None
        self._sequence = 0
        self._started = False

    def _url(self) -> str:
        params = {
            "encoding": "mulaw",
            "sample_rate": "8000",
            "channels": "1",
            "model": self._model,
            "language": self._language,
            "punctuate": "true",
            "smart_format": "true",
            "interim_results": "false",
            "endpointing": "300",
        }
        return f"{_DEEPGRAM_URL}?{urlencode(params)}"

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        import websockets

        self._ws = await websockets.connect(
            self._url(),
            additional_headers={"Authorization": f"Token {self._api_key}"},
            max_size=None,
        )
        self._reader = asyncio.create_task(self._read_loop())
        self._keepalive = asyncio.create_task(self._keepalive_loop())
        logger.info("deepgram session open call=%s track=%s", self._call_sid, self._track)

    async def feed(self, mulaw_frame: bytes, timestamp_ms: int) -> None:
        if not self._started or self._ws is None:
            return
        try:
            await self._ws.send(mulaw_frame)
        except Exception:  # noqa: BLE001 - a dropped socket must not kill the call
            logger.warning("audio send failed call=%s track=%s", self._call_sid, self._track)

    async def close(self) -> None:
        if not self._started:
            return
        self._started = False
        for task in (self._keepalive, self._reader):
            if task is not None:
                task.cancel()
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.send(json.dumps({"type": "CloseStream"}))
                await self._ws.close()
        for task in (self._keepalive, self._reader):
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        logger.info("deepgram session closed call=%s track=%s", self._call_sid, self._track)

    async def _keepalive_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(_KEEPALIVE_SECONDS)
                if self._ws is not None:
                    with contextlib.suppress(Exception):
                        await self._ws.send(json.dumps({"type": "KeepAlive"}))
        except asyncio.CancelledError:
            raise

    async def _read_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                await self._handle(json.loads(raw))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("read loop ended call=%s track=%s", self._call_sid, self._track)

    async def _handle(self, message: dict[str, Any]) -> None:
        if message.get("type") == "Error":
            logger.error(
                "deepgram error call=%s track=%s detail=%s",
                self._call_sid,
                self._track,
                message,
            )
            return
        if message.get("type") != "Results" or not message.get("is_final"):
            return
        alternatives = message.get("channel", {}).get("alternatives", [])
        text = alternatives[0].get("transcript", "").strip() if alternatives else ""
        if not text:
            return
        await self._emit(text, int(float(message.get("start", 0.0)) * 1000))

    async def _emit(self, text: str, audio_offset_ms: int) -> None:
        self._sequence += 1
        event = TranscriptEvent(
            call_sid=self._call_sid,
            event_key=build_event_key(self._call_sid, self._track, self._sequence),
            track=self._track,
            speaker=self._speaker,
            sequence_number=self._sequence,
            audio_offset_ms=max(audio_offset_ms, 0),
            text=text,
            is_final=True,
        )
        await self._on_event(event)

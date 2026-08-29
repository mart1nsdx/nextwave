"""Deepgram Aura-2 streaming synthesis, emitting mu-law 8 kHz straight to the phone.

encoding=mulaw & sample_rate=8000 means the bytes Deepgram produces go to Twilio with no
conversion step. That is the reason this vendor is the default: any 24 kHz voice would
need resampling, and `audioop` — the obvious tool — is deprecated in 3.12 and gone in 3.13.

Voice selection is config (TTS_MODEL). The Aura-2 voices that switch between English and
Spanish mid-sentence are aquila, carina, diana, javier and selena, which matters because
a dispatcher in Guadalajara will mix both in one breath.
"""

import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import structlog
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from . import TtsSession

log = structlog.get_logger(__name__)

SPEAK_URL = "wss://api.deepgram.com/v1/speak"


class DeepgramTtsSession:
    def __init__(self, socket: ClientConnection) -> None:
        self._socket = socket

    async def speak(self, text: str) -> None:
        await self._send({"type": "Speak", "text": text})

    async def flush(self) -> None:
        await self._send({"type": "Flush"})

    async def clear(self) -> None:
        await self._send({"type": "Clear"})

    async def audio(self) -> AsyncIterator[bytes]:
        try:
            async for raw in self._socket:
                # Binary frames are audio; JSON frames are Metadata/Flushed/Cleared/Warning.
                if isinstance(raw, bytes):
                    yield raw
        except ConnectionClosed:
            return

    async def close(self) -> None:
        await self._send({"type": "Close"})
        await self._socket.close()

    async def _send(self, message: dict[str, str]) -> None:
        try:
            await self._socket.send(json.dumps(message))
        except ConnectionClosed:
            pass


class DeepgramTts:
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise ValueError("DEEPGRAM_API_KEY is empty — the agent would have no voice.")
        self._api_key = api_key
        self._query = urlencode({"model": model, "encoding": "mulaw", "sample_rate": "8000"})

    async def connect(self) -> DeepgramTtsSession:
        socket = await connect(
            f"{SPEAK_URL}?{self._query}",
            additional_headers={"Authorization": f"Token {self._api_key}"},
        )
        log.info("tts_connected", provider="deepgram")
        return DeepgramTtsSession(socket)


if TYPE_CHECKING:

    def _conforms(socket: ClientConnection) -> TtsSession:
        return DeepgramTtsSession(socket)

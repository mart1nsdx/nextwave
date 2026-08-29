"""Speech synthesis, normalised across vendors.

The shape mirrors voice/stt/: text in, mu-law frames out, plus the two controls that
barge-in needs — `clear` to abandon audio the counterparty interrupted, and `flush` to
force out the tail of a turn.
"""

from collections.abc import AsyncIterator
from typing import Protocol

from app.config import Settings


class TtsSession(Protocol):
    """One synthesizer connection, for one call."""

    async def speak(self, text: str) -> None:
        """Queue text. Called per clause, so audio starts before the sentence ends."""

    async def flush(self) -> None:
        """Force out whatever is buffered — the end of the agent's turn."""

    async def clear(self) -> None:
        """Abandon buffered audio. Half of the barge-in cut; the other half is the sink."""

    def audio(self) -> AsyncIterator[bytes]:
        """Yield mu-law frames as they are generated."""
        ...

    async def close(self) -> None: ...


class TtsProvider(Protocol):
    async def connect(self) -> TtsSession: ...


def make_tts(settings: Settings) -> TtsProvider:
    """Pick a synthesizer from configuration. See make_stt for why the import is local."""
    if settings.tts_provider == "deepgram":
        from .deepgram import DeepgramTts

        return DeepgramTts(api_key=settings.deepgram_api_key, model=settings.tts_model)
    if settings.tts_provider == "fake":
        from .fake import FakeTts

        return FakeTts()
    raise ValueError(f"TTS_PROVIDER={settings.tts_provider!r} is not one of: deepgram, fake")

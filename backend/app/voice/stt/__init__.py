"""Speech recognition, normalised across vendors.

MAY IMPORT:  domain, config, agent, tools (this is part of voice/).

Every recognizer reports roughly the same four things under different names and shapes.
`SttSession` is the contract the pipeline actually depends on; a vendor module translates
its own protocol into voice/events.py types and nothing upstream learns the vendor exists.

That indirection is not speculative. STT accuracy on a noisy Mexican phone line is the
single largest risk to the demo and is not knowable in advance, so switching vendors has
to be a config change at 3am rather than a rewrite (docs/DECISION_LOG.md D7).
"""

from collections.abc import AsyncIterator
from typing import Protocol

from app.config import Settings

from ..events import SttEvent
from ..frames import InboundFrame


class SttSession(Protocol):
    """One recognizer connection, for one call.

    Audio in, events out, and a close. Anything a vendor needs beyond that — API keys,
    reconnects, keepalives, its own JSON — is the vendor module's problem.
    """

    async def send(self, frame: InboundFrame) -> None:
        """Feed one frame of counterparty audio."""

    def events(self) -> AsyncIterator[SttEvent]:
        """Yield events until the session closes. Ends when the call does."""
        ...

    async def close(self) -> None:
        """Stop recognising and let events() finish."""


class SttProvider(Protocol):
    """Opens a session per call. Holds the configuration; holds no per-call state."""

    async def connect(self) -> SttSession: ...


def make_stt(settings: Settings) -> SttProvider:
    """Pick a recognizer from configuration. One line to change vendors mid-hackathon."""
    # Imported inside the function, not at module scope: the vendor modules import this
    # one for the Protocol, and nothing should pull a websocket client into memory just
    # because someone imported a type.
    if settings.stt_provider == "deepgram":
        from .deepgram import DeepgramStt

        return DeepgramStt(
            api_key=settings.deepgram_api_key,
            model=settings.stt_model,
            language=settings.stt_language,
            endpointing_ms=settings.vad_endpointing_ms,
            utterance_end_ms=settings.vad_utterance_end_ms,
        )
    if settings.stt_provider == "fake":
        # Silent by default. sim_call and tests build FakeStt with a real script.
        from .fake import FakeStt

        return FakeStt(())
    raise ValueError(f"STT_PROVIDER={settings.stt_provider!r} is not one of: deepgram, fake")

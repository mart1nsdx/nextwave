"""Provider-neutral contract for real-time speech-to-text."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudioFrame:
    call_sid: str
    track: str
    timestamp_ms: str | None
    mulaw_8khz: bytes


class StreamingTranscriber(Protocol):
    async def push(self, frame: AudioFrame) -> None:
        """Accept one Twilio audio frame without blocking the WebSocket."""

    async def close(self, call_sid: str) -> None:
        """Flush a call and emit any final transcript."""


class LoggingTranscriber:
    """Safe placeholder until a real STT provider and its key are selected."""

    async def push(self, frame: AudioFrame) -> None:
        logger.debug("STT frame call=%s track=%s bytes=%d", frame.call_sid, frame.track, len(frame.mulaw_8khz))

    async def close(self, call_sid: str) -> None:
        logger.info("STT session closed call=%s", call_sid)

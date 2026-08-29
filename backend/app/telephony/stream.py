"""Twilio Media Streams <-> the transport Protocols in voice/frames.py.

This is the only file that knows Twilio's WebSocket protocol. Everything upstream of it
sees mu-law frames and nothing else, which is what keeps the pipeline testable without a
phone line and what would let a SIP backend replace Twilio without touching voice/.

Protocol reference: Twilio sends `connected`, `start`, `media`, `dtmf`, `stop`, `mark`;
a bidirectional stream accepts `media`, `mark`, and `clear` back.
"""

import asyncio
import base64
import json
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

import structlog
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.voice.frames import InboundFrame

log = structlog.get_logger(__name__)

_END_OF_STREAM = None

# A coroutine function, not merely an awaitable: TaskGroup.create_task requires one.
FrameConsumer = Callable[["MediaStreamTransport"], Coroutine[Any, Any, None]]


class MediaStreamTransport:
    """One live call's audio, in both directions.

    Implements voice.frames.AudioSource and voice.frames.AudioSink. `pump()` owns the
    single WebSocket read loop and must run concurrently with whoever consumes
    `frames()` — the router starts both in a task group.
    """

    def __init__(self, websocket: WebSocket) -> None:
        self._ws = websocket
        self._inbound: asyncio.Queue[InboundFrame | None] = asyncio.Queue()
        self._stream_sid = ""
        self._call_sid = ""
        self._last_offset_ms = 0
        self._pending_marks: set[str] = set()
        self._started = asyncio.Event()

    # --- identity ---------------------------------------------------------------

    @property
    def call_id(self) -> str:
        """Twilio's CallSid. Named call_id because that is the log field everywhere."""
        return self._call_sid

    @property
    def stream_sid(self) -> str:
        return self._stream_sid

    @property
    def last_offset_ms(self) -> int:
        """Stream position of the most recent inbound frame, in milliseconds.

        Twilio's own presentation timestamp, not a wall clock we computed. This is the
        anchor a commitment is eventually pinned to (invariant #3), so it must come from
        the media stream rather than from time.monotonic() on our side.
        """
        return self._last_offset_ms

    @property
    def pending_marks(self) -> frozenset[str]:
        """Marks sent but not yet played back. Non-empty means the agent is still audible."""
        return frozenset(self._pending_marks)

    async def wait_until_started(self) -> None:
        """Block until Twilio's `start` event has given us the streamSid."""
        await self._started.wait()

    # --- AudioSource ------------------------------------------------------------

    async def frames(self) -> AsyncIterator[InboundFrame]:
        while True:
            frame = await self._inbound.get()
            if frame is _END_OF_STREAM:
                return
            yield frame

    # --- AudioSink --------------------------------------------------------------

    async def send_audio(self, payload: bytes) -> None:
        """Queue mu-law bytes for playback on the call."""
        if not payload:
            return
        await self._send(
            {
                "event": "media",
                "streamSid": self._stream_sid,
                "media": {"payload": base64.b64encode(payload).decode("ascii")},
            }
        )

    async def clear(self) -> None:
        """Drop everything queued but not yet played. The barge-in cut.

        Twilio responds by returning the `mark` messages for the audio it dropped, so
        pending marks are abandoned here rather than waiting for playback that will
        never happen.
        """
        self._pending_marks.clear()
        await self._send({"event": "clear", "streamSid": self._stream_sid})
        log.info("audio_cleared", call_id=self._call_sid, offset_ms=self._last_offset_ms)

    async def mark(self, name: str) -> None:
        """Ask Twilio to tell us when everything queued so far has finished playing."""
        self._pending_marks.add(name)
        await self._send({"event": "mark", "streamSid": self._stream_sid, "mark": {"name": name}})

    # --- the read loop ----------------------------------------------------------

    async def pump(self) -> None:
        """Read the WebSocket until the call ends. Runs for the lifetime of the call."""
        try:
            while True:
                message: dict[str, Any] = json.loads(await self._ws.receive_text())
                event = message.get("event")

                if event == "media":
                    media = message["media"]
                    self._last_offset_ms = int(media["timestamp"])
                    await self._inbound.put(
                        InboundFrame(
                            payload=base64.b64decode(media["payload"]),
                            offset_ms=self._last_offset_ms,
                        )
                    )
                elif event == "start":
                    start = message["start"]
                    self._stream_sid = message.get("streamSid", start.get("streamSid", ""))
                    self._call_sid = start.get("callSid", "")
                    self._started.set()
                    log.info("stream_started", call_id=self._call_sid, stream_sid=self._stream_sid)
                elif event == "mark":
                    self._pending_marks.discard(message["mark"]["name"])
                elif event == "dtmf":
                    log.info(
                        "dtmf",
                        call_id=self._call_sid,
                        digit=message["dtmf"]["digit"],
                        offset_ms=self._last_offset_ms,
                    )
                elif event == "stop":
                    log.info("stream_stopped", call_id=self._call_sid)
                    return
                elif event == "connected":
                    continue
        except WebSocketDisconnect:
            log.info("stream_disconnected", call_id=self._call_sid)
        finally:
            self._started.set()  # never leave a waiter hanging on a dead call
            await self._inbound.put(_END_OF_STREAM)

    async def pump_with(self, consumer: FrameConsumer) -> None:
        """Run the read loop and a consumer of frames() together, for the life of the call.

        Both are required and neither works alone: pump() fills a queue nobody drains,
        and a consumer never receives a frame. Bundling them means no caller can start
        just one half and then wonder why the line is silent.
        """
        async with asyncio.TaskGroup() as group:
            group.create_task(self.pump())
            group.create_task(consumer(self))

    async def _send(self, message: dict[str, Any]) -> None:
        """Write to the socket, tolerating a call that hung up underneath us.

        A dropped call is the normal end of every conversation, not an error worth
        propagating into the pipeline.
        """
        if self._ws.client_state is not WebSocketState.CONNECTED or not self._stream_sid:
            return
        try:
            await self._ws.send_text(json.dumps(message))
        except (WebSocketDisconnect, RuntimeError):
            log.info("send_after_close", call_id=self._call_sid, event=message.get("event"))

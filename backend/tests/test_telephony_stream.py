"""The Twilio Media Streams adapter, driven by a fake socket. No network, no PSTN."""

import base64
import json
from collections import deque
from typing import Any

import pytest
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.telephony.idempotency import SeenEvents
from app.telephony.router import echo
from app.telephony.stream import MediaStreamTransport
from app.telephony.twiml import connect_stream, websocket_url

CALL_SID = "CA0123456789abcdef"
STREAM_SID = "MZ0123456789abcdef"


class FakeWebSocket:
    """Replays a scripted Twilio message sequence, then hangs up like a real call does."""

    def __init__(self, incoming: list[dict[str, Any]]) -> None:
        self._incoming = deque(json.dumps(m) for m in incoming)
        self.sent: list[dict[str, Any]] = []
        self.client_state = WebSocketState.CONNECTED

    async def receive_text(self) -> str:
        if not self._incoming:
            self.client_state = WebSocketState.DISCONNECTED
            raise WebSocketDisconnect(code=1000)
        return self._incoming.popleft()

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))


def _start() -> dict[str, Any]:
    return {
        "event": "start",
        "streamSid": STREAM_SID,
        "start": {"streamSid": STREAM_SID, "callSid": CALL_SID},
    }


def _media(payload: bytes, timestamp: int) -> dict[str, Any]:
    return {
        "event": "media",
        "streamSid": STREAM_SID,
        "media": {
            "track": "inbound",
            "timestamp": str(timestamp),
            "payload": base64.b64encode(payload).decode("ascii"),
        },
    }


async def test_echo_returns_the_same_audio() -> None:
    payloads = [b"\x01" * 160, b"\x02" * 160, b"\x03" * 160]
    socket = FakeWebSocket(
        [{"event": "connected"}, _start()]
        + [_media(p, 20 * (i + 1)) for i, p in enumerate(payloads)]
        + [{"event": "stop", "streamSid": STREAM_SID}]
    )
    transport = MediaStreamTransport(socket)  # type: ignore[arg-type]

    await transport.pump_with(echo)

    returned = [
        base64.b64decode(m["media"]["payload"]) for m in socket.sent if m["event"] == "media"
    ]
    assert returned == payloads
    assert all(m["streamSid"] == STREAM_SID for m in socket.sent)


async def test_offsets_come_from_twilio_not_from_our_clock() -> None:
    """Invariant #3 anchors commitments to stream position, so it must survive transport."""
    seen: list[int] = []

    async def collect(t: MediaStreamTransport) -> None:
        async for frame in t.frames():
            seen.append(frame.offset_ms)

    socket = FakeWebSocket(
        [_start(), _media(b"\xff" * 160, 20), _media(b"\xff" * 160, 40), {"event": "stop"}]
    )
    transport = MediaStreamTransport(socket)  # type: ignore[arg-type]
    await transport.pump_with(collect)

    assert seen == [20, 40]
    assert transport.last_offset_ms == 40
    assert transport.call_sid == CALL_SID


async def test_clear_abandons_pending_marks() -> None:
    """Barge-in drops queued audio, so its marks will never play back."""
    socket = FakeWebSocket([_start(), {"event": "stop"}])
    transport = MediaStreamTransport(socket)  # type: ignore[arg-type]

    async def speak_then_interrupt(t: MediaStreamTransport) -> None:
        await t.wait_until_started()
        await t.send_audio(b"\xff" * 160)
        await t.mark("turn-1")
        assert t.pending_marks == frozenset({"turn-1"})
        await t.clear()
        assert t.pending_marks == frozenset()

    await transport.pump_with(speak_then_interrupt)
    assert [m["event"] for m in socket.sent] == ["media", "mark", "clear"]


async def test_call_that_hangs_up_mid_sentence_is_not_an_error() -> None:
    """The normal end of every conversation. It must not propagate as an exception."""
    socket = FakeWebSocket([_start()])  # no stop event: the line just drops
    transport = MediaStreamTransport(socket)  # type: ignore[arg-type]
    await transport.pump_with(echo)


def test_status_redelivery_is_a_no_op() -> None:
    """Invariant #7: Twilio retries, the second delivery must do nothing."""
    seen = SeenEvents()
    assert seen.record(f"{CALL_SID}:completed") is True
    assert seen.record(f"{CALL_SID}:completed") is False
    assert seen.record(f"{CALL_SID}:answered") is True


def test_stream_url_is_wss_because_twilio_rejects_anything_else() -> None:
    assert websocket_url("https://abc.ngrok.app") == "wss://abc.ngrok.app/twilio/media"
    assert websocket_url("https://abc.ngrok.app/") == "wss://abc.ngrok.app/twilio/media"


def test_twiml_connects_a_bidirectional_stream() -> None:
    xml = connect_stream("wss://abc.ngrok.app/twilio/media")
    # <Connect>, not <Start>: only Connect can carry audio back and accept `clear`.
    assert "<Connect>" in xml
    assert '<Stream url="wss://abc.ngrok.app/twilio/media"' in xml


def test_missing_public_base_url_fails_loudly() -> None:
    """Invariant #6: a config gap must not degrade into a call that silently goes dead."""
    with pytest.raises(ValueError, match="PUBLIC_BASE_URL"):
        websocket_url("")


def test_voice_webhook_hands_the_call_to_our_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    """The one request that must never fail: a wrong answer here is a dead phone line."""
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://volta-demo.ngrok.app")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        response = client.post(
            "/twilio/voice",
            data={"CallSid": CALL_SID, "From": "+523312345678", "To": "+523398765432"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/xml")
        assert '<Stream url="wss://volta-demo.ngrok.app/twilio/media"' in response.text
    finally:
        get_settings.cache_clear()

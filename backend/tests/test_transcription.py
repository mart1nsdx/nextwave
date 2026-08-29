"""RealtimeTranscriber event handling. No network.

The transcriber's job on the receive side is to parse Deepgram ``Results`` events into
domain TranscriptEvents with a stable idempotency key and an audio offset (from the
event's ``start`` seconds). We drive ``_handle`` directly with recorded payloads.
"""

from app.domain.models import Speaker, TranscriptEvent, TranscriptTrack
from app.realtime.transcriber import RealtimeTranscriber


class _Capture:
    def __init__(self) -> None:
        self.events: list[TranscriptEvent] = []

    async def __call__(self, event: TranscriptEvent) -> None:
        self.events.append(event)


def _transcriber(
    sink: _Capture, track: TranscriptTrack = TranscriptTrack.INBOUND
) -> RealtimeTranscriber:
    return RealtimeTranscriber(
        api_key="test-key",
        model="nova-3",
        language="multi",
        call_sid="CA9",
        track=track,
        on_event=sink,
    )


def _results(transcript: str, *, start: float, is_final: bool = True) -> dict:
    return {
        "type": "Results",
        "start": start,
        "is_final": is_final,
        "channel": {"alternatives": [{"transcript": transcript}]},
    }


async def test_final_result_becomes_a_transcript_event() -> None:
    capture = _Capture()
    t = _transcriber(capture)
    await t._handle(_results("ocho mil quinientos pesos", start=3.2))

    assert len(capture.events) == 1
    event = capture.events[0]
    assert event.text == "ocho mil quinientos pesos"
    assert event.is_final is True
    assert event.speaker is Speaker.CALLER
    assert event.audio_offset_ms == 3200
    assert event.event_key == "CA9:inbound:1"


async def test_interim_results_are_ignored() -> None:
    capture = _Capture()
    t = _transcriber(capture)
    await t._handle(_results("ocho mil", start=3.0, is_final=False))
    assert capture.events == []


async def test_blank_final_is_dropped() -> None:
    capture = _Capture()
    t = _transcriber(capture)
    await t._handle(_results("   ", start=1.0))
    assert capture.events == []


async def test_outbound_track_is_attributed_to_the_agent() -> None:
    capture = _Capture()
    t = _transcriber(capture, track=TranscriptTrack.OUTBOUND)
    await t._handle(_results("le puedo cotizar el jueves", start=0.5))
    assert capture.events[0].speaker is Speaker.AGENT
    assert capture.events[0].event_key == "CA9:outbound:1"


async def test_sequence_numbers_increase_per_track() -> None:
    capture = _Capture()
    t = _transcriber(capture)
    for i in range(3):
        await t._handle(_results(f"frase {i}", start=float(i)))
    assert [e.sequence_number for e in capture.events] == [1, 2, 3]
    assert [e.event_key for e in capture.events] == [
        "CA9:inbound:1",
        "CA9:inbound:2",
        "CA9:inbound:3",
    ]


async def test_non_results_messages_are_ignored() -> None:
    capture = _Capture()
    t = _transcriber(capture)
    await t._handle({"type": "Metadata", "request_id": "x"})
    await t._handle({"type": "UtteranceEnd", "last_word_end": 4.1})
    assert capture.events == []

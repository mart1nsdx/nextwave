"""The audio behind the offset.

Every commitment records the millisecond it was agreed at. That number is only evidence if
there is a recording to seek into — otherwise the audit trail asserts a timestamp nobody
can check. These tests cover the hook that connects the two.
"""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.repo import InMemoryTranscriptStore


def _client(store: InMemoryTranscriptStore) -> TestClient:
    app = create_app(
        settings=Settings(public_base_url="https://volta.ngrok.app"),
        store=store,
        recap_model=None,  # never reached: no call is completed in these tests
    )
    return TestClient(app)


async def test_a_finished_recording_is_stored_against_its_call() -> None:
    store = InMemoryTranscriptStore()
    client = _client(store)
    client.post("/twilio/voice", data={"CallSid": "CArec", "Direction": "outbound"})

    response = client.post(
        "/twilio/recording",
        data={
            "CallSid": "CArec",
            "RecordingSid": "REabc",
            "RecordingUrl": "https://api.twilio.com/REabc",
            "RecordingDuration": "214",
        },
    )

    assert response.status_code == 204
    recordings = await store.list_recordings("CArec")
    assert len(recordings) == 1
    assert recordings[0]["provider_recording_id"] == "REabc"
    # Twilio reports whole seconds; the rest of the system measures in milliseconds, and
    # mixing the two units is how a playback seek lands 200x off.
    assert recordings[0]["duration_ms"] == 214_000


async def test_recording_webhook_redelivery_is_idempotent() -> None:
    """UGLY_CASES row 12, for this hook. Twilio retries; the second must be a no-op."""
    store = InMemoryTranscriptStore()
    client = _client(store)
    client.post("/twilio/voice", data={"CallSid": "CArec", "Direction": "outbound"})
    payload = {"CallSid": "CArec", "RecordingSid": "REabc", "RecordingDuration": "10"}

    client.post("/twilio/recording", data=payload)
    client.post("/twilio/recording", data=payload)

    assert len(await store.list_recordings("CArec")) == 1


async def test_a_recording_hook_without_ids_is_ignored_rather_than_crashing() -> None:
    store = InMemoryTranscriptStore()
    client = _client(store)

    assert client.post("/twilio/recording", data={}).status_code == 204
    assert await store.list_recordings("CArec") == []

"""Handoff policy, evidence, and TwiML are testable without a PSTN call."""

from app.domain.models import HandoffReason, HandoffStatus
from app.repo import InMemoryTranscriptStore
from app.telephony.twiml import caller_hold_conference, operator_brief, operator_join_conference
from app.tools import HandoffTool, detected_handoff_reason


async def test_direct_handoff_request_is_idempotent() -> None:
    store = InMemoryTranscriptStore()
    calls: list[str] = []

    async def execute(request: object) -> None:
        calls.append("executed")

    tool = HandoffTool(store, execute)
    first = await tool.propose_handoff(
        "CAhandoff", HandoffReason.DIRECT_REQUEST, 120, "caller asked for a person"
    )
    second = await tool.propose_handoff(
        "CAhandoff", HandoffReason.DIRECT_REQUEST, 120, "caller asked for a person"
    )

    assert first is not None
    assert second is None
    assert calls == ["executed"]
    assert await store.get_handoff_for_call("CAhandoff") == first
    events = await store.list_handoff_events(str(first.handoff_id))
    assert [event.status for event in events] == [HandoffStatus.AUTHORIZED]


def test_direct_request_detector_and_outside_mandate_detector() -> None:
    assert detected_handoff_reason("Quiero hablar con una persona") is HandoffReason.DIRECT_REQUEST
    assert detected_handoff_reason("Mi jefe ya autorizó el precio") is HandoffReason.OUTSIDE_MANDATE
    assert detected_handoff_reason("La fecha es el jueves") is None


def test_warm_handoff_twiml_requires_operator_confirmation() -> None:
    hold = caller_hold_conference("volta-handoff-abc", "https://example/wait", "https://example/status")
    brief = operator_brief("https://example/accept", "Marque uno para aceptar.")
    join = operator_join_conference("volta-handoff-abc", "https://example/status")

    assert 'startConferenceOnEnter="false"' in hold
    assert 'waitUrl="https://example/wait"' in hold
    assert '<Gather action="https://example/accept"' in brief
    assert 'numDigits="1"' in brief
    assert 'startConferenceOnEnter="true"' in join

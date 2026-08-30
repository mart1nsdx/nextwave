"""A call is bound to one case and one mandate, or it does not happen at all.

The failure these tests exist for is the quietest one in the system. Before this, every
call — inbound included — ran the demo operation under the demo ceiling, because that was
the only operation the code could name. Nothing raised: the agent negotiated confidently
on behalf of a company the caller had never contracted with, against a cap that belonged
to a different shipment. A demo looks identical either way.

So the assertions here are about the two things that make it not identical: the mandate
that governs a call is the one bound to *that* call, and a call whose case cannot be
established unambiguously gets a person rather than a default.
"""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.binding import CallBinding
from app.domain.models import (
    CallBrief,
    CallDirection,
    HandoffReason,
    Recap,
    RecapContext,
    Speaker,
    TranscriptTrack,
)
from app.domain.security import CommitmentMode, Mandate
from app.ledger import EvidenceLedger
from app.main import InMemoryCaseBindings, create_app
from app.policy import quote_escalation_reason
from app.repo import InMemoryTranscriptStore
from app.telephony.handoff import TwilioHandoff
from app.telephony.router import create_router
from app.telephony.stream import MediaStreamTransport
from app.telephony.twiml import connect_stream
from app.voice.session import build_session

CALL_SID = "CA0123456789abcdef"
STREAM_SID = "MZ0123456789abcdef"
CARRIER_NUMBER = "+523312345678"


def _mandate(mandate_id: str, operation_id: str, ceiling: str) -> Mandate:
    return Mandate(
        mandate_id=mandate_id,
        version=1,
        owner_id="textiles-pacifico/ops",
        operation_id=operation_id,
        max_all_in_usd=Decimal(ceiling),
        pickup_not_before=datetime(2026, 9, 2, 6, 0, tzinfo=UTC),
        pickup_not_after=datetime(2026, 9, 4, 23, 59, tzinfo=UTC),
        allowed_equipment=frozenset({"chasis de 40 pies"}),
        commitment_mode=CommitmentMode.HUMAN_ESCALATION,
    )


def _binding(case_id: str, operation_ref: str, ceiling: str) -> CallBinding:
    return CallBinding(
        case_id=case_id,
        operation_ref=operation_ref,
        direction=CallDirection.OUTBOUND,
        mandate=_mandate(f"MND-{operation_ref}", operation_ref, ceiling),
    )


# --------------------------------------------------------- the mandate governs the call


def test_a_quote_allowed_under_one_mandate_escalates_under_another() -> None:
    """The point of the whole item, in four lines.

    If the same number can be accepted on one call and must be escalated on another, then
    the authority really did travel with the case. If it could not, the cap would be a
    constant and binding would be decoration.
    """
    generous = _mandate("MND-A", "OP-1042", "9000")
    tight = _mandate("MND-B", "OP-2077", "8000")
    quoted = Decimal("8800")

    assert quote_escalation_reason(generous, quoted) is None
    assert quote_escalation_reason(tight, quoted) is HandoffReason.OUTSIDE_MANDATE


def test_two_sessions_built_from_two_bindings_hold_two_different_caps() -> None:
    """Two live calls, two cases. Neither session can see the other's authority."""
    from app.agent import DEMO_PROFILE, CallPhase, demo_context

    settings = Settings(
        stt_provider="fake",
        tts_provider="fake",
        openai_api_key="sk-test-not-a-real-key",
        openai_agent_model="gpt-test",
    )
    context = demo_context(CallPhase.RFQ)

    first = _binding("case-a", "OP-1042", "9000")
    second = _binding("case-b", "OP-2077", "8000")
    session_a = build_session(settings, DEMO_PROFILE, context, first)
    session_b = build_session(settings, DEMO_PROFILE, context, second)

    assert session_a.binding is not None and session_b.binding is not None
    cap_a = session_a.binding.mandate.max_all_in_usd
    cap_b = session_b.binding.mandate.max_all_in_usd
    assert cap_a != cap_b

    # And the caps are not merely different labels: the same quote lands on opposite
    # sides of them.
    quoted = Decimal("8800")
    assert quote_escalation_reason(session_a.binding.mandate, quoted) is None
    assert (
        quote_escalation_reason(session_b.binding.mandate, quoted) is HandoffReason.OUTSIDE_MANDATE
    )


def test_the_case_reaches_the_prompt_the_agent_actually_speaks_from() -> None:
    """Binding that stops at the session boundary has not bound anything."""
    from app.agent import DEMO_PROFILE, CallPhase, build_system_prompt, demo_context

    binding = _binding("case-b", "OP-2077", "8000")
    context = demo_context(CallPhase.RFQ).model_copy(update={"reference": binding.operation_ref})

    assert "Reference: OP-2077" in build_system_prompt(DEMO_PROFILE, context)


# ------------------------------------------------------------ the case id on the wire


def test_the_case_id_rides_on_the_twiml_stream() -> None:
    xml = connect_stream("wss://abc.ngrok.app/twilio/media", case_id="case-abc123")
    assert '<Parameter name="case_id" value="case-abc123"' in xml


def test_an_inbound_call_gets_no_case_parameter_because_it_has_no_case() -> None:
    assert "<Parameter" not in connect_stream("wss://abc.ngrok.app/twilio/media")


async def test_custom_parameters_arrive_with_the_first_stream_message() -> None:
    """No CallSid correlation and no database read — hence no race to lose."""
    socket = _FakeWebSocket(
        [
            {
                "event": "start",
                "streamSid": STREAM_SID,
                "start": {
                    "streamSid": STREAM_SID,
                    "callSid": CALL_SID,
                    "customParameters": {"case_id": "case-abc123"},
                },
            },
            {"event": "stop"},
        ]
    )
    transport = MediaStreamTransport(socket)  # type: ignore[arg-type]

    seen: dict[str, str] = {}

    async def read(active: MediaStreamTransport) -> None:
        await active.wait_until_started()
        seen.update(active.custom_parameters)

    await transport.pump_with(read)

    assert seen == {"case_id": "case-abc123"}


# ---------------------------------------------------------------------- fail closed


async def test_an_unresolvable_call_escalates_instead_of_running_a_default_mandate() -> None:
    """Invariant #6. The one branch that must never be allowed to degrade into a guess."""
    escalations: list[tuple[str, HandoffReason, str]] = []
    sessions_built: list[CallBinding] = []

    async def resolve_nothing(call_sid: str, custom: Mapping[str, str]) -> CallBinding | None:
        return None

    client = _router_client(resolve_nothing, escalations, sessions_built)
    with client.websocket_connect("/twilio/media") as socket:
        socket.send_text(json.dumps(_start()))
        socket.send_text(json.dumps({"event": "stop"}))

    assert sessions_built == [], "an unbound call must not open a conversation at all"
    assert escalations == [
        (
            CALL_SID,
            HandoffReason.AMBIGUOUS_CRITICAL_TERM,
            "call could not be bound to exactly one case",
        )
    ]


async def test_a_resolved_call_opens_a_session_on_its_own_binding() -> None:
    """The other half: fail-closed is only a virtue if the open path still works."""
    escalations: list[tuple[str, HandoffReason, str]] = []
    sessions_built: list[CallBinding] = []
    expected = _binding("case-abc123", "OP-2077", "8000")

    async def resolve_from_parameter(
        call_sid: str, custom: Mapping[str, str]
    ) -> CallBinding | None:
        return expected if custom.get("case_id") == expected.case_id else None

    client = _router_client(resolve_from_parameter, escalations, sessions_built)
    with client.websocket_connect("/twilio/media") as socket:
        socket.send_text(json.dumps(_start(custom={"case_id": "case-abc123"})))
        socket.send_text(json.dumps({"event": "stop"}))

    assert escalations == []
    assert [binding.operation_ref for binding in sessions_built] == ["OP-2077"]


# ----------------------------------------------------------------- resolution order


async def test_a_call_we_placed_identifies_itself_from_its_stream_parameter() -> None:
    bindings = InMemoryCaseBindings(InMemoryTranscriptStore())
    case_id = await bindings.reserve(CARRIER_NUMBER)

    resolved = await bindings.resolve(CALL_SID, {"case_id": case_id})

    assert resolved is not None
    assert resolved.case_id == case_id
    assert resolved.call_sid == CALL_SID


async def test_a_stream_naming_a_case_we_do_not_have_escalates() -> None:
    """A forged or stale parameter is not a reason to fall back to something else."""
    bindings = InMemoryCaseBindings(InMemoryTranscriptStore())

    assert await bindings.resolve(CALL_SID, {"case_id": "case-not-ours"}) is None


async def test_an_inbound_call_is_correlated_by_the_number_that_called() -> None:
    store = InMemoryTranscriptStore()
    bindings = InMemoryCaseBindings(store)
    case_id = await bindings.reserve(CARRIER_NUMBER)
    # The carrier calls us back from the number we dialled, so there is no case_id.
    await store.open_case(CALL_SID, CallDirection.INBOUND, from_number=CARRIER_NUMBER)

    resolved = await bindings.resolve(CALL_SID, {})

    assert resolved is not None
    assert resolved.case_id == case_id
    assert resolved.direction is CallDirection.INBOUND


async def test_an_inbound_call_from_an_unknown_number_escalates() -> None:
    store = InMemoryTranscriptStore()
    bindings = InMemoryCaseBindings(store)
    await bindings.reserve(CARRIER_NUMBER)
    await store.open_case(CALL_SID, CallDirection.INBOUND, from_number="+525599998888")

    assert await bindings.resolve(CALL_SID, {}) is None


async def test_two_candidate_cases_for_one_number_is_an_escalation_not_a_choice() -> None:
    """Ambiguity is an explicit event (invariant #4), never a last-write-wins pick."""
    store = InMemoryTranscriptStore()
    bindings = InMemoryCaseBindings(store)
    await bindings.reserve(CARRIER_NUMBER)
    await bindings.reserve(CARRIER_NUMBER)
    await store.open_case(CALL_SID, CallDirection.INBOUND, from_number=CARRIER_NUMBER)

    assert await bindings.resolve(CALL_SID, {}) is None


async def test_the_case_is_written_before_the_number_is_dialled() -> None:
    """Ordering, not decoration.

    Twilio can answer and open the media stream before `calls.create` has returned to us.
    A case written afterwards would leave that stream resolving against a case that does
    not exist yet — and failing closed on a call we ourselves authorized.
    """
    bindings = InMemoryCaseBindings(InMemoryTranscriptStore())

    case_id = await bindings.reserve(CARRIER_NUMBER)
    # The stream can already resolve, with no CallSid known to us anywhere.
    early = await bindings.resolve("CAearly", {"case_id": case_id})
    assert early is not None and early.operation_ref

    await bindings.bind(case_id, CALL_SID)
    assert (await bindings.resolve(CALL_SID, {})) is not None


# ------------------------------------------------------------------- the recap knows


class _RecordingReportModel:
    def __init__(self) -> None:
        self.contexts: list[RecapContext] = []

    async def summarize(self, transcript: str, context: RecapContext) -> Recap:
        self.contexts.append(context)
        return Recap(call_sid="", summary="ok")

    async def brief(self, transcript: str) -> CallBrief:
        return CallBrief(call_sid="")


async def test_the_recap_is_told_which_case_it_is_summarizing() -> None:
    """An empty RecapContext produces a report that cannot name its own operation."""
    store = InMemoryTranscriptStore()
    model = _RecordingReportModel()
    app = create_app(
        settings=Settings(public_base_url="https://volta.ngrok.app"),
        store=store,
        recap_model=model,
    )
    bindings: InMemoryCaseBindings = app.state.case_bindings
    case_id = await bindings.reserve(CARRIER_NUMBER)
    await bindings.bind(case_id, CALL_SID)

    await store.open_case(CALL_SID, CallDirection.OUTBOUND, to_number=CARRIER_NUMBER)
    await EvidenceLedger(store).record_segment(
        CALL_SID,
        track=TranscriptTrack.INBOUND,
        sequence_number=1,
        audio_offset_ms=1200,
        text="nueve mil pesos",
        is_final=True,
        speaker=Speaker.CALLER,
    )

    response = TestClient(app).post(f"/calls/{CALL_SID}/recap")

    assert response.status_code == 200
    assert len(model.contexts) == 1
    context = model.contexts[0]
    assert context.operation_ref == "OP-1042"
    assert context.mandate_summary is not None
    assert "MND-1042" in context.mandate_summary


# ------------------------------------------------------------------------- fixtures


def _start(custom: dict[str, str] | None = None) -> dict[str, Any]:
    start: dict[str, Any] = {"streamSid": STREAM_SID, "callSid": CALL_SID}
    if custom is not None:
        start["customParameters"] = custom
    return {"event": "start", "streamSid": STREAM_SID, "start": start}


class _FakeWebSocket:
    """Replays a scripted Twilio message sequence, then hangs up like a real call does."""

    def __init__(self, incoming: list[dict[str, Any]]) -> None:
        from collections import deque

        from starlette.websockets import WebSocketState

        self._incoming = deque(json.dumps(m) for m in incoming)
        self.sent: list[dict[str, Any]] = []
        self.client_state = WebSocketState.CONNECTED

    async def receive_text(self) -> str:
        from starlette.websockets import WebSocketDisconnect, WebSocketState

        if not self._incoming:
            self.client_state = WebSocketState.DISCONNECTED
            raise WebSocketDisconnect(code=1000)
        return self._incoming.popleft()

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))


class _NoopSession:
    """Stands in for a VoiceSession. It only has to prove it was built and started."""

    async def run(self, source: object, sink: object) -> None:
        return None


def _router_client(
    resolve_case: Any,
    escalations: list[tuple[str, HandoffReason, str]],
    sessions_built: list[CallBinding],
) -> TestClient:
    settings = Settings(public_base_url="https://volta.ngrok.app")
    store = InMemoryTranscriptStore()

    async def on_call_finished(call_sid: str) -> None:
        return None

    async def on_final(*args: Any, **kwargs: Any) -> None:
        return None

    async def on_handoff(call_sid: str, reason: HandoffReason, offset: int, note: str) -> bool:
        escalations.append((call_sid, reason, note))
        return True

    def make_session(binding: CallBinding) -> Any:
        sessions_built.append(binding)
        return _NoopSession()

    class _NoOutbound:
        async def reserve(self, to_number: str) -> str:
            raise AssertionError("this test never dials")

        async def bind(self, case_id: str, call_sid: str) -> None:
            raise AssertionError("this test never dials")

    app = FastAPI()
    app.include_router(
        create_router(
            settings,
            store,
            on_call_finished,
            on_final,
            TwilioHandoff(settings, store),
            on_handoff,
            make_session,
            resolve_case,
            _NoOutbound(),
        )
    )
    return TestClient(app)

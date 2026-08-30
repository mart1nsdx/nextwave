"""Control-tower projections and operator commands never place a PSTN call."""

from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.config import Settings
from app.domain import (
    ActivationRequest,
    AwardRequest,
    BotConfiguration,
    CallEvidence,
    CallSummary,
    CarrierCandidate,
    CommandResult,
    CommitmentMode,
    CommitmentState,
    CommitmentSummary,
    EvidencePointer,
    FxSnapshot,
    Mandate,
    MandateSummary,
    OfferComparison,
    OperationConfiguration,
    OperationSummary,
    OperationWorkspace,
    PolicyDecisionSummary,
    ReadinessCheck,
    RfqPhase,
    RfqSummary,
    TranscriptLine,
    TrustedSessionIdentity,
)
from app.main import create_app
from app.market.control_tower import ControlTowerService
from app.policy.control_tower import evaluate_rfq_activation
from app.repo import SupabaseControlTowerRepository


class ControlTowerTestRepository:
    """Test-only deterministic store; the application itself uses Supabase."""

    def __init__(self) -> None:
        self.workspaces = {
            "operation-at-risk": _workspace("operation-at-risk", RfqPhase.READY, "needs_attention"),
            "operation-working": _workspace("operation-working", RfqPhase.OPEN, "working"),
            "operation-executing": _workspace("operation-executing", RfqPhase.CLOSED, "executing"),
        }
        self.commands: dict[str, CommandResult] = {}
        self.call = CallSummary(
            id="call-1",
            operation_id="operation-working",
            carrier_name="Carrier One",
            direction="Outbound RFQ",
            status="Completed",
            started_at=_moment(),
            duration_seconds=120,
            summary="Confirmed an all-in offer and pickup window.",
            has_evidence=True,
            is_demo=False,
        )

    def list_operations(self) -> list[OperationSummary]:
        priority = {"needs_attention": 0, "working": 1, "executing": 2}
        return sorted(
            [_summary(workspace) for workspace in self.workspaces.values()],
            key=lambda item: priority[item.attention],
        )

    def get_workspace(self, operation_id: str) -> OperationWorkspace | None:
        workspace = self.workspaces.get(operation_id)
        return workspace.model_copy(deep=True) if workspace else None

    def get_calls(self, operation_id: str) -> list[CallSummary]:
        return [self.call] if operation_id == self.call.operation_id else []

    def list_calls(self) -> list[CallSummary]:
        return [self.call]

    def get_evidence(self, call_id: str) -> CallEvidence | None:
        if call_id != self.call.id:
            return None
        return CallEvidence(
            call=self.call,
            call_brief=["Evidence remains attached to the original call."],
            transcript=[
                TranscriptLine(
                    offset_ms=104_000,
                    speaker="Carrier",
                    text="The total is final and the pickup window is confirmed.",
                    is_relevant=True,
                )
            ],
            policy_decisions=[
                PolicyDecisionSummary(
                    verdict="Allow", reason_code="TERMS_WITHIN_MANDATE", decided_at=_moment()
                )
            ],
            recap_status="Sent",
            evidence=EvidencePointer(
                recording_id="recording-1",
                audio_offset_ms=104_000,
                transcript_event_id="event-1",
                audio_url="https://evidence.example.test/recording-1",
            ),
            is_demo=False,
        )

    def get_configuration(self, operation_id: str) -> OperationConfiguration | None:
        if operation_id not in self.workspaces:
            return None
        return OperationConfiguration(
            operation_id=operation_id,
            bot=BotConfiguration(
                agent_name="Volta",
                agent_role="transport coordinator",
                primary_language="en",
                fallback_language="es-MX",
                recap_channel="email",
            ),
            mandate=Mandate(
                mandate_id=f"MANDATE-{operation_id}-V1",
                version=1,
                owner_id="customer-1",
                operation_id=operation_id,
                max_all_in_usd=Decimal("600"),
                pickup_not_before=_moment(),
                pickup_not_after=datetime(2026, 8, 30, 23, 59, tzinfo=UTC),
                allowed_equipment=frozenset({"40-foot container chassis"}),
                commitment_mode=CommitmentMode.HUMAN_ESCALATION,
                fx_margin_bps=500,
            ),
            fx_snapshots=[
                FxSnapshot(
                    snapshot_id="FX-1",
                    quote_currency="MXN",
                    usd_per_unit=Decimal("0.054"),
                    observed_at=_moment(),
                    source="approved-provider",
                )
            ],
            trusted_session=TrustedSessionIdentity(
                trusted_carrier_name="Carrier One",
                trusted_carrier_id="carrier-1",
                trusted_contact_id="contact-1",
            ),
            is_demo=False,
        )

    def get_command(self, idempotency_key: str) -> CommandResult | None:
        return self.commands.get(idempotency_key)

    def activate_rfq(
        self, operation_id: str, carrier_ids: list[str], idempotency_key: str
    ) -> CommandResult:
        previous = self.commands.get(idempotency_key)
        if previous:
            return previous
        workspace = self.workspaces[operation_id]
        self.workspaces[operation_id] = workspace.model_copy(
            update={
                "rfq": workspace.rfq.model_copy(
                    update={"phase": RfqPhase.OPEN, "carrier_ids": carrier_ids}
                ),
                "stage": "RFQ in progress",
                "attention": "working",
            }
        )
        result = CommandResult(
            operation_id=operation_id,
            rfq_id=workspace.rfq.id,
            outcome="activated",
            message="RFQ activation recorded.",
            phase=RfqPhase.OPEN,
            is_demo=False,
        )
        self.commands[idempotency_key] = result
        return result

    def request_award(
        self, operation_id: str, offer_id: str, idempotency_key: str
    ) -> CommandResult:
        previous = self.commands.get(idempotency_key)
        if previous:
            return previous
        workspace = self.workspaces[operation_id]
        self.workspaces[operation_id] = workspace.model_copy(
            update={"rfq": workspace.rfq.model_copy(update={"phase": RfqPhase.AWARDING})}
        )
        result = CommandResult(
            operation_id=operation_id,
            rfq_id=workspace.rfq.id,
            outcome="award_requested",
            message="Award request recorded; the commitment remains unbooked.",
            phase=RfqPhase.AWARDING,
            is_demo=False,
        )
        self.commands[idempotency_key] = result
        return result


def _service() -> ControlTowerService:
    return ControlTowerService(ControlTowerTestRepository())


def _moment() -> datetime:
    return datetime(2026, 8, 29, 12, tzinfo=UTC)


def _workspace(operation_id: str, phase: RfqPhase, attention: str) -> OperationWorkspace:
    offers = (
        [
            OfferComparison(
                id="offer-1",
                carrier_id="carrier-1",
                carrier_name="Carrier One",
                freight_amount_minor=55_000,
                expected_total_amount_minor=60_000,
                currency="USD",
                pickup_window="30 Aug, 09:00–12:00",
                reliability_percent=95,
                status="eligible",
                rationale="The earliest reliable option remains within the mandate.",
                is_recommended=True,
            )
        ]
        if phase is RfqPhase.OPEN
        else []
    )
    return OperationWorkspace(
        id=operation_id,
        reference=f"REF-{operation_id}",
        client_name="Customer One",
        container_number="CONT-1",
        bill_of_lading="BOL-1",
        cargo_description="Cargo",
        weight_kg=1_000,
        route="Origin → Destination",
        ocean_carrier="Ocean carrier",
        last_free_day="30 Aug 2026",
        days_remaining=3,
        stage="RFQ ready" if phase is RfqPhase.READY else "RFQ in progress",
        attention=attention,
        next_action="Review the operation.",
        signals=[],
        timeline=[],
        readiness=[
            ReadinessCheck(
                label="Mandate", status="Active", detail="Ready", is_ready=True, source="policy"
            )
        ],
        mandate=MandateSummary(
            version=1,
            cap_amount_minor=60_000,
            currency="USD",
            pickup_window="30 Aug, 09:00–12:00",
            status="active",
            authorized_actions=["start_rfq", "request_award"],
        ),
        carrier_candidates=[
            CarrierCandidate(
                id="carrier-1",
                name="Carrier One",
                reliability_percent=95,
                is_vetted=True,
                rationale="Vetted",
            ),
            CarrierCandidate(
                id="carrier-2",
                name="Carrier Two",
                reliability_percent=94,
                is_vetted=True,
                rationale="Vetted",
            ),
            CarrierCandidate(
                id="carrier-3",
                name="Carrier Three",
                reliability_percent=93,
                is_vetted=True,
                rationale="Vetted",
            ),
        ],
        rfq=RfqSummary(id=f"rfq-{operation_id}", phase=phase, offers=offers),
        commitment=CommitmentSummary(state=CommitmentState.NONE),
        connected_agents=[],
        is_demo=False,
    )


def _summary(workspace: OperationWorkspace) -> OperationSummary:
    return OperationSummary(
        id=workspace.id,
        reference=workspace.reference,
        client_name=workspace.client_name,
        container_number=workspace.container_number,
        route=workspace.route,
        stage=workspace.stage,
        attention=workspace.attention,
        days_remaining=workspace.days_remaining,
        next_action=workspace.next_action,
        source_freshness="Updated from source",
        source_is_demo=False,
    )


def test_operations_are_prioritized_by_attention() -> None:
    operations = _service().list_operations()

    assert [operation.attention for operation in operations] == [
        "needs_attention",
        "working",
        "executing",
    ]
    assert operations[0].days_remaining == 3
    assert operations[0].source_is_demo is False


def test_rfq_activation_requires_a_full_vetted_market_and_is_idempotent() -> None:
    service = _service()
    workspace = service.get_workspace("operation-at-risk")
    assert workspace is not None

    denied = service.activate_rfq(
        workspace.id,
        workspace.rfq.id,
        ActivationRequest(carrier_ids=["carrier-1"], idempotency_key="too-few"),
    )
    activated = service.activate_rfq(
        workspace.id,
        workspace.rfq.id,
        ActivationRequest(
            carrier_ids=["carrier-1", "carrier-2", "carrier-3"], idempotency_key="activate-once"
        ),
    )
    replay = service.activate_rfq(
        workspace.id,
        workspace.rfq.id,
        ActivationRequest(carrier_ids=["carrier-1"], idempotency_key="activate-once"),
    )

    assert denied.outcome == "denied"
    assert "CARRIER_MARKET_INCOMPLETE" in denied.message
    assert activated.outcome == "activated"
    assert replay == activated
    assert service.get_workspace(workspace.id).rfq.phase is RfqPhase.OPEN  # type: ignore[union-attr]


def test_rfq_activation_requires_an_active_mandate_and_three_distinct_vetted_carriers() -> None:
    workspace = _service().get_workspace("operation-at-risk")
    assert workspace is not None

    inactive = workspace.model_copy(
        update={"mandate": workspace.mandate.model_copy(update={"status": "inactive"})}
    )
    vetted_carriers = ["carrier-1", "carrier-2", "carrier-3"]
    duplicate_carriers = ["carrier-1", "carrier-1", "carrier-1"]

    assert evaluate_rfq_activation(inactive, vetted_carriers).reason_code == "MANDATE_INACTIVE"
    assert (
        evaluate_rfq_activation(workspace, duplicate_carriers).reason_code
        == "CARRIER_MARKET_INCOMPLETE"
    )


def test_award_request_locks_the_market_without_creating_a_commitment() -> None:
    service = _service()
    workspace = service.get_workspace("operation-working")
    assert workspace is not None

    result = service.request_award(
        workspace.id,
        workspace.rfq.id,
        AwardRequest(offer_id="offer-1", idempotency_key="award-once"),
    )
    replay = service.request_award(
        workspace.id,
        workspace.rfq.id,
        AwardRequest(offer_id="offer-1", idempotency_key="award-once"),
    )
    updated = service.get_workspace(workspace.id)

    assert result.outcome == "award_requested"
    assert replay == result
    assert updated is not None
    assert updated.rfq.phase is RfqPhase.AWARDING
    assert updated.commitment.state == "none"


def test_dashboard_api_serves_a_workspace_configuration_and_evidence() -> None:
    client = TestClient(create_app(_service()))

    operations = client.get("/operations")
    configuration = client.get("/operations/operation-at-risk/configuration")
    evidence = client.get("/calls/call-1/evidence")

    assert operations.status_code == 200
    assert configuration.json()["mandate"]["operation_id"] == "operation-at-risk"
    assert configuration.json()["mandate"]["fx_margin_bps"] == 500
    assert evidence.json()["evidence"]["audio_offset_ms"] == 104_000


def test_unknown_operation_or_evidence_returns_a_readable_not_found_response() -> None:
    client = TestClient(create_app(_service()))

    assert client.get("/operations/unknown/workspace").status_code == 404
    assert client.get("/calls/unknown/evidence").status_code == 404


def test_unconfigured_production_repository_fails_closed_instead_of_using_fixture_data() -> None:
    service = ControlTowerService(SupabaseControlTowerRepository(Settings()))
    client = TestClient(create_app(service))

    response = client.get("/operations")

    assert response.status_code == 503
    assert (
        response.json()["detail"] == "The control tower database is not configured on this server."
    )

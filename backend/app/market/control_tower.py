"""Operator command orchestration for the dashboard control tower.

This service is intentionally small. It turns an authenticated operator request into a
policy decision and only then asks persistence to record the result. It never dials a
carrier or writes a commitment; those responsibilities remain in their own layers.
"""

from __future__ import annotations

from app.domain import (
    ActivationRequest,
    AwardRequest,
    CallEvidence,
    CallSummary,
    CommandResult,
    OperationConfiguration,
    OperationSummary,
    OperationWorkspace,
)
from app.policy.control_tower import evaluate_award_request, evaluate_rfq_activation
from app.repo.control_tower import ControlTowerRepository

__all__ = ["ControlTowerService"]


class ControlTowerService:
    def __init__(self, repository: ControlTowerRepository) -> None:
        self._repository = repository

    def list_operations(self) -> list[OperationSummary]:
        return self._repository.list_operations()

    def get_workspace(self, operation_id: str) -> OperationWorkspace | None:
        return self._repository.get_workspace(operation_id)

    def get_calls(self, operation_id: str) -> list[CallSummary]:
        return self._repository.get_calls(operation_id)

    def list_calls(self) -> list[CallSummary]:
        return self._repository.list_calls()

    def get_evidence(self, call_id: str) -> CallEvidence | None:
        return self._repository.get_evidence(call_id)

    def get_configuration(self, operation_id: str) -> OperationConfiguration | None:
        return self._repository.get_configuration(operation_id)

    def activate_rfq(
        self, operation_id: str, rfq_id: str, request: ActivationRequest
    ) -> CommandResult:
        previous = self._repository.get_command(request.idempotency_key)
        if previous:
            return previous

        workspace = self._workspace_for_rfq(operation_id, rfq_id)
        decision = evaluate_rfq_activation(workspace, request.carrier_ids)
        if not decision.allowed:
            return CommandResult(
                operation_id=operation_id,
                rfq_id=rfq_id,
                outcome="denied",
                message=f"RFQ activation was denied: {decision.reason_code}.",
                phase=workspace.rfq.phase,
            )
        return self._repository.activate_rfq(
            operation_id, request.carrier_ids, request.idempotency_key
        )

    def request_award(self, operation_id: str, rfq_id: str, request: AwardRequest) -> CommandResult:
        previous = self._repository.get_command(request.idempotency_key)
        if previous:
            return previous

        workspace = self._workspace_for_rfq(operation_id, rfq_id)
        decision = evaluate_award_request(workspace, request.offer_id)
        if not decision.allowed:
            return CommandResult(
                operation_id=operation_id,
                rfq_id=rfq_id,
                outcome="denied",
                message=f"Award request was denied: {decision.reason_code}.",
                phase=workspace.rfq.phase,
            )
        return self._repository.request_award(
            operation_id, request.offer_id, request.idempotency_key
        )

    def _workspace_for_rfq(self, operation_id: str, rfq_id: str) -> OperationWorkspace:
        workspace = self._repository.get_workspace(operation_id)
        if workspace is None or workspace.rfq.id != rfq_id:
            raise KeyError(operation_id)
        return workspace

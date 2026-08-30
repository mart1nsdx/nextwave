"""Deterministic authorization for operator-initiated control-tower commands."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain import OperationWorkspace, RfqPhase

__all__ = ["ControlTowerDecision", "evaluate_award_request", "evaluate_rfq_activation"]


@dataclass(frozen=True)
class ControlTowerDecision:
    """A compact policy result; the market layer owns the resulting state write."""

    allowed: bool
    reason_code: str


def evaluate_rfq_activation(
    workspace: OperationWorkspace, carrier_ids: list[str]
) -> ControlTowerDecision:
    """Allow an RFQ only when its immutable operational prerequisites are present."""
    if workspace.rfq.phase is not RfqPhase.READY:
        return ControlTowerDecision(False, "RFQ_NOT_READY")
    if workspace.mandate.status != "active":
        return ControlTowerDecision(False, "MANDATE_INACTIVE")
    if "start_rfq" not in workspace.mandate.authorized_actions:
        return ControlTowerDecision(False, "ACTION_NOT_AUTHORIZED")
    if not all(check.is_ready for check in workspace.readiness):
        return ControlTowerDecision(False, "READINESS_INCOMPLETE")
    selected_carrier_ids = set(carrier_ids)
    if len(selected_carrier_ids) < 3:
        return ControlTowerDecision(False, "CARRIER_MARKET_INCOMPLETE")

    vetted_carriers = {carrier.id for carrier in workspace.carrier_candidates if carrier.is_vetted}
    if not selected_carrier_ids.issubset(vetted_carriers):
        return ControlTowerDecision(False, "CARRIER_NOT_VETTED")
    return ControlTowerDecision(True, "RFQ_ACTIVATION_ALLOWED")


def evaluate_award_request(workspace: OperationWorkspace, offer_id: str) -> ControlTowerDecision:
    """Protect the market lock: award requests are separate from quote gathering."""
    if workspace.rfq.phase is not RfqPhase.OPEN:
        return ControlTowerDecision(False, "RFQ_NOT_OPEN")
    if workspace.mandate.status != "active":
        return ControlTowerDecision(False, "MANDATE_INACTIVE")
    if "request_award" not in workspace.mandate.authorized_actions:
        return ControlTowerDecision(False, "ACTION_NOT_AUTHORIZED")

    offer = next((item for item in workspace.rfq.offers if item.id == offer_id), None)
    if offer is None:
        return ControlTowerDecision(False, "OFFER_NOT_FOUND")
    if offer.status != "eligible":
        return ControlTowerDecision(False, "OFFER_NOT_ELIGIBLE")
    return ControlTowerDecision(True, "AWARD_REQUEST_ALLOWED")

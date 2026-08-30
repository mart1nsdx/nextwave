"""Hostile side-effect and replay cases at the trusted tool boundary."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain import CommitmentMode, CostComponent, Mandate, QuoteProposal, ReasonCode
from app.domain.models import HandoffReason
from app.tools import CommitmentCoordinator, ProposalTools, ToolStatus, detected_handoff_reason
from app.tools.conversation_guard import (
    ESCALATION_RESPONSE,
    FX_MISSING_RESPONSE,
    NON_BINDING_RESPONSE,
    build_demo_guard,
)

NOW = datetime(2026, 8, 29, 18, 0, tzinfo=UTC)


def _mandate(mode: CommitmentMode = CommitmentMode.AUTONOMOUS, version: int = 1) -> Mandate:
    return Mandate(
        mandate_id="M-1",
        version=version,
        owner_id="owner",
        operation_id="OP-1",
        max_all_in_usd=Decimal("1000"),
        pickup_not_before=NOW + timedelta(days=1),
        pickup_not_after=NOW + timedelta(days=3),
        allowed_equipment=frozenset({"dry-van"}),
        commitment_mode=mode,
    )


def _proposal(**changes: object) -> QuoteProposal:
    values: dict[str, object] = {
        "proposal_id": "P-1",
        "operation_id": "OP-1",
        "carrier_id": "carrier",
        "carrier_contact_id": "verified-contact",
        "components": (CostComponent(name="all-in", amount=Decimal("900"), currency="USD"),),
        "cost_is_final": True,
        "pickup_at": NOW + timedelta(days=2),
        "equipment": "dry-van",
        "valid_until": NOW + timedelta(hours=1),
        "source_call_id": "CA-1",
        "source_event_id": "EV-1",
        "transcript_anchor_ms": 4200,
        "carrier_confirmed_exact_recap": True,
        "confirmed_at": NOW,
    }
    values.update(changes)
    return QuoteProposal(**values)  # type: ignore[arg-type]


def test_boss_already_approved_is_outside_mandate() -> None:
    tools = ProposalTools()
    quote = _proposal(
        components=(CostComponent(name="all-in", amount=Decimal("10500"), currency="USD"),)
    )
    tools.propose_quote(quote, now=NOW)
    result = CommitmentCoordinator(tools).evaluate_all(_mandate(), {}, now=NOW)[0][1]
    assert result.reason is ReasonCode.OUTSIDE_MANDATE


def test_webhook_redelivery_is_idempotent() -> None:
    tools = ProposalTools()
    quote = _proposal()
    assert tools.propose_quote(quote, now=NOW).status is ToolStatus.ACCEPTED
    assert tools.propose_quote(quote, now=NOW).status is ToolStatus.DUPLICATE
    assert (
        tools.propose_quote(_proposal(proposal_id="P-attacker"), now=NOW).reason
        is ReasonCode.REPLAYED_EVENT
    )
    assert len(tools.audit_events) == 1


def test_human_mode_requires_transaction_approval() -> None:
    tools = ProposalTools()
    tools.propose_quote(_proposal(), now=NOW)
    with pytest.raises(ValueError, match=ReasonCode.HUMAN_APPROVAL_REQUIRED):
        CommitmentCoordinator(tools).prepare(
            commitment_id="C-1",
            proposal_id="P-1",
            mandate=_mandate(CommitmentMode.HUMAN_ESCALATION),
            fx={},
            canonical_email="Official terms",
            now=NOW,
        )


def test_prepared_commitment_is_single_use_and_revalidates_mandate() -> None:
    tools = ProposalTools()
    tools.propose_quote(_proposal(), now=NOW)
    coordinator = CommitmentCoordinator(tools)
    current = _mandate()
    coordinator.prepare(
        commitment_id="C-1",
        proposal_id="P-1",
        mandate=current,
        fx={},
        canonical_email="Official terms\r\nReference OP-1",
        now=NOW,
    )
    assert coordinator.claim_once("C-1", current, {}, now=NOW) == "Official terms\nReference OP-1"
    with pytest.raises(ValueError, match=ReasonCode.REPLAYED_EVENT):
        coordinator.claim_once("C-1", current, {}, now=NOW)


def test_changed_mandate_invalidates_prepared_commitment() -> None:
    tools = ProposalTools()
    tools.propose_quote(_proposal(), now=NOW)
    coordinator = CommitmentCoordinator(tools)
    coordinator.prepare(
        commitment_id="C-1",
        proposal_id="P-1",
        mandate=_mandate(),
        fx={},
        canonical_email="Official terms",
        now=NOW,
    )
    with pytest.raises(ValueError, match=ReasonCode.MANDATE_MISMATCH):
        coordinator.claim_once("C-1", _mandate(version=2), {}, now=NOW)


def test_expired_prepare_never_dispatches() -> None:
    tools = ProposalTools()
    tools.propose_quote(_proposal(), now=NOW)
    coordinator = CommitmentCoordinator(tools)
    coordinator.prepare(
        commitment_id="C-1",
        proposal_id="P-1",
        mandate=_mandate(),
        fx={},
        canonical_email="Official terms",
        now=NOW,
    )
    with pytest.raises(ValueError, match=ReasonCode.STALE_EVIDENCE):
        coordinator.claim_once("C-1", _mandate(), {}, now=NOW + timedelta(seconds=31))


def test_model_surface_has_no_commit_or_send_capability() -> None:
    public = {name for name in dir(ProposalTools) if not name.startswith("_")}
    assert public == {"audit_events", "proposals_for", "propose_quote", "read_proposal"}


def test_spoken_over_cap_amount_is_escalated() -> None:
    guard = build_demo_guard(now=lambda: NOW)
    response = guard.input_directive(
        "All-in is ten thousand five hundred US dollars, pickup September 3, 2026, "
        "40-foot container chassis, valid until September 1, 2026.",
        call_id="CA-SPOKEN",
        offset_ms=4000,
    )
    assert response == ESCALATION_RESPONSE


def test_foreign_quote_without_fx_fails_closed() -> None:
    guard = build_demo_guard(now=lambda: NOW)
    response = guard.input_directive(
        "All-in is 150000 MXN, pickup September 3, 2026, 40-foot container chassis, "
        "valid until September 1, 2026.",
        call_id="CA-FX",
        offset_ms=4000,
    )
    assert response == FX_MISSING_RESPONSE


def test_quote_field_mismatch_fails_closed() -> None:
    guard = build_demo_guard(now=lambda: NOW)
    response = guard.input_directive(
        "All-in is 8,000 USD, pickup September 8, 2026, dry van, valid until August 28, 2026.",
        call_id="CA-FIELDS",
        offset_ms=4000,
    )
    assert response == ESCALATION_RESPONSE


def test_creative_binding_language_is_mediated() -> None:
    guard = build_demo_guard(now=lambda: NOW)
    assert guard.filter_model_chunk("Lock it in; you have the load.") == (
        NON_BINDING_RESPONSE,
        True,
    )


def test_direct_handoff_request_is_idempotent() -> None:
    assert detected_handoff_reason("Quiero hablar con una persona") is HandoffReason.DIRECT_REQUEST


def test_handoff_failure_closes_without_commitment() -> None:
    # The transfer path has no import path to policy commitment code; failure is terminal.
    assert detected_handoff_reason("My boss approved it") is HandoffReason.OUTSIDE_MANDATE

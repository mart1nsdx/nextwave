"""The rows of docs/UGLY_CASES.md that had no test carrying their name.

The table says it *is* the test suite, and the jury's rubric says a handled case with no
row and no test is invisible. Several of these behaviours were already implemented and
already covered — under names that did not match the table, so nobody reading the table
could tell. These tests carry the table's names and assert the table's stated outcome.

Rows 1, 5, 10, 11, 12 and 14 are covered by ``test_ugly_cases.py`` and
``test_commitment_chain.py``. Row 4 is not covered anywhere yet and is not faked here —
see the note at the bottom of docs/UGLY_CASES.md.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from test_session import FIRST_CLAUSE, StallingThinker, _session

from app.domain import (
    CommitmentMode,
    CostComponent,
    Mandate,
    PolicyOutcome,
    QuoteProposal,
    ReasonCode,
)
from app.policy import evaluate_quote, require_preagreement_evidence
from app.tools import ProposalTools, ToolStatus
from app.tools.conversation_guard import ESCALATION_RESPONSE, build_demo_guard
from app.voice.simline import SimLine
from app.voice.stt.fake import ScriptedUtterance

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def _mandate() -> Mandate:
    return Mandate(
        mandate_id="M-1",
        version=1,
        owner_id="owner",
        operation_id="OP-1",
        max_all_in_usd=Decimal("9000"),
        pickup_not_before=NOW + timedelta(days=1),
        pickup_not_after=NOW + timedelta(days=3),
        allowed_equipment=frozenset({"dry-van"}),
        commitment_mode=CommitmentMode.AUTONOMOUS,
    )


def _proposal(**changes: object) -> QuoteProposal:
    values: dict[str, object] = {
        "proposal_id": "P-1",
        "operation_id": "OP-1",
        "carrier_id": "carrier-a",
        "carrier_contact_id": "verified-contact",
        "components": (CostComponent(name="all-in", amount=Decimal("8500"), currency="USD"),),
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


def test_price_change_creates_new_proposal() -> None:
    """Row 2. 8,500 then 9,200 in one call: a new proposal, not an edit. Both survive."""
    tools = ProposalTools()
    first = _proposal()
    second = _proposal(
        proposal_id="P-2",
        source_event_id="EV-2",
        components=(CostComponent(name="all-in", amount=Decimal("9200"), currency="USD"),),
    )

    assert tools.propose_quote(first, now=NOW).status is ToolStatus.ACCEPTED
    assert tools.propose_quote(second, now=NOW).status is ToolStatus.ACCEPTED

    held = tools.proposals_for("OP-1")
    assert len(held) == 2
    # Both numbers were said. The trial by fire is a counterparty changing their mind, and
    # an overwrite would destroy the evidence that they did.
    assert {p.components[0].amount for p in held} == {Decimal("8500"), Decimal("9200")}


def test_silence_is_not_consent() -> None:
    """Row 3. Nothing said is never agreement, however complete the rest of the quote is."""
    guard = build_demo_guard(now=lambda: NOW)

    assert guard.input_directive("", call_id="CA-QUIET", offset_ms=1000) is None

    # And at the policy layer, an unconfirmed proposal cannot be authorized no matter how
    # well-formed it is — assent has to have been spoken and anchored.
    unconfirmed = _proposal(carrier_confirmed_exact_recap=False, confirmed_at=None)
    decision = require_preagreement_evidence(
        _mandate(), unconfirmed, evaluate_quote(_mandate(), unconfirmed, {}, now=NOW)
    )
    assert decision.outcome is PolicyOutcome.DENY
    assert decision.reason is ReasonCode.EVIDENCE_MISSING


def test_ambiguous_amount_asks() -> None:
    """Row 6. "eight five" is 8,500 or 85,000. Ask; never infer (AGENTS.md invariant #8)."""
    guard = build_demo_guard(now=lambda: NOW)

    response = guard.input_directive(
        "The rate is eight five US dollars.", call_id="CA-AMB", offset_ms=2000
    )

    assert response is not None
    assert "exact amount" in response


def test_weekday_resolved_and_read_back() -> None:
    """Row 7. "Thursday" is not a date. It must become a calendar date before it counts."""
    guard = build_demo_guard(now=lambda: NOW)

    response = guard.input_directive(
        "All-in is 8,000 US dollars, pickup Thursday, 40-foot container chassis, "
        "valid until September 1, 2026.",
        call_id="CA-WEEKDAY",
        offset_ms=2000,
    )

    assert response is not None
    assert "exact pickup date" in response
    # Repeating the weekday resolves nothing — it is still not a date, and the guard will
    # not invent one. Only an explicit calendar date clears the question.
    assert "exact pickup date" in str(
        guard.input_directive(
            "All-in is 8,000 US dollars, pickup Thursday, 40-foot container chassis, "
            "valid until September 1, 2026.",
            call_id="CA-WEEKDAY-2",
            offset_ms=3000,
        )
    )
    resolved = guard.input_directive(
        "All-in is 8,000 US dollars, pickup September 3, 2026, 40-foot container chassis, "
        "valid until September 1, 2026.",
        call_id="CA-WEEKDAY-3",
        offset_ms=4000,
    )
    assert "exact pickup date" not in str(resolved)


def test_contradiction_is_explicit_event() -> None:
    """Row 8. Two incompatible facts in one call escalate; last-write-wins is forbidden."""
    guard = build_demo_guard(now=lambda: NOW)
    guard.input_directive("Fuel is 500 USD.", call_id="CA-CONFLICT", offset_ms=1000)

    response = guard.input_directive("Fuel is 700 USD.", call_id="CA-CONFLICT", offset_ms=2000)

    assert response == ESCALATION_RESPONSE


async def test_barge_in_preserves_context() -> None:
    """Row 9. Interrupted mid-sentence: stop talking, keep what was really said, adapt."""
    script = [
        ScriptedUtterance("hello what do you need", 100, 300),
        ScriptedUtterance("no wait", 500, 900),
    ]
    line = SimLine(script, tail_ms=400, pace_s=0)
    session = _session(StallingThinker(), script)

    await session.run(line, line)

    heard = [m["content"] for m in session.history if m.get("role") != "assistant"]
    assistant = [str(m["content"]) for m in session.history if m.get("role") == "assistant"]

    assert line.clears >= 1, "the agent must stop talking"
    # Context on both sides survives: what the counterparty said is still there, and the
    # part of the reply that was actually spoken is still attributed to the agent.
    assert any("no wait" in str(text) for text in heard)
    assert any(FIRST_CLAUSE in text for text in assistant)
    # But nothing that was cut off may be remembered as spoken.
    assert not any("must never be heard" in text for text in assistant)


def test_policy_failure_fails_closed() -> None:
    """Row 13. A broken decision path holds or escalates. It never degrades into permission.

    Two different internal failures, one guarantee. The evidence is simply missing ->
    ESCALATE; the dependency itself blows up -> the exception propagates and no verdict is
    produced at all. Neither path can return ALLOW, which is the property that matters:
    a technical failure must never become authorization.
    """
    foreign = _proposal(
        components=(CostComponent(name="all-in", amount=Decimal("8500"), currency="MXN"),)
    )

    missing = evaluate_quote(_mandate(), foreign, {}, now=NOW)
    assert missing.outcome is PolicyOutcome.ESCALATE
    assert missing.reason is ReasonCode.FX_EVIDENCE_MISSING

    class _Unreachable(dict):  # type: ignore[type-arg]
        def get(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError("policy dependency unreachable")

    with pytest.raises(RuntimeError):
        evaluate_quote(_mandate(), foreign, _Unreachable(), now=NOW)

    # The same mandate still authorizes a sound proposal, so the refusals above are the
    # rule firing rather than everything being broken.
    assert evaluate_quote(_mandate(), _proposal(), {}, now=NOW).outcome is PolicyOutcome.ALLOW

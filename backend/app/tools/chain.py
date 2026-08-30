"""Where a policy verdict becomes a row, and a recap becomes a commitment.

This is the composition step the demo is judged on. Everything it needs already existed
separately — ``policy/`` reaches verdicts, ``repo/`` writes rows, ``notify/`` sends the
recap — and none of them were connected, so the system reached "recap generated" and
stopped one step short of the two facts the brief actually asks for: a commitment written
to the operation's state, and a written recap that has gone out.

The order below is the whole point and is not an implementation detail:

    evaluate  ->  a decision row, always, including the denials
              ->  ALLOW only: a commitment in VERBAL, anchored to the audio offset
              ->  send the recap
              ->  delivered: RECAP_SENT -> COMMITTED
              ->  not delivered: RECAP_FAILED, and the commitment never counted

A failure to send is not a partial success. `RECAP_FAILED` is terminal here and the
interface must not render it as firm (AGENTS.md invariant #3, ugly case #10).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

import structlog

from app.domain import (
    FxSnapshot,
    Mandate,
    PolicyDecision,
    PolicyOutcome,
    QuoteProposal,
    Recap,
    RecapDeliveryStatus,
    RecapSender,
)
from app.domain.commitment import ChainState, DecisionRow, OfferRow, usd_to_minor
from app.domain.ports import OperationStore
from app.policy import evaluate_quote, require_preagreement_evidence

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SettlementResult:
    """What actually happened, in terms a dashboard can render without interpreting."""

    decision: PolicyDecision
    decision_id: str
    offer_id: str | None = None
    commitment_id: str | None = None
    state: ChainState | None = None

    @property
    def committed(self) -> bool:
        return self.state is ChainState.COMMITTED


class CommitmentChain:
    """Turns one confirmed proposal into operation state, or into a recorded refusal."""

    def __init__(
        self,
        operations: OperationStore,
        sender: RecapSender,
        *,
        recap_to_email: str,
    ) -> None:
        self._ops = operations
        self._sender = sender
        self._recap_to = recap_to_email

    async def settle(
        self,
        *,
        mandate: Mandate,
        proposal: QuoteProposal,
        fx: Mapping[str, FxSnapshot],
        recap: Recap,
        rfq_id: str,
        participant_segment_id: str,
        now: datetime,
    ) -> SettlementResult:
        decision = require_preagreement_evidence(
            mandate, proposal, evaluate_quote(mandate, proposal, fx, now=now)
        )
        bound = log.bind(
            call_id=proposal.source_call_id,
            proposal_id=proposal.proposal_id,
            outcome=decision.outcome.value,
            reason=decision.reason.value,
        )

        # The denial rows are written before anything else and are never conditional. They
        # are the only way to *show* a refusal during the trial by fire rather than assert
        # one after the fact.
        decision_id = await self._ops.record_decision(
            DecisionRow(
                operation_id=mandate.operation_id,
                verdict=_verdict(decision.outcome),
                reason_code=decision.reason.value,
                proposal=proposal.model_dump(mode="json"),
                call_sid=proposal.source_call_id,
                mandate_id=mandate.mandate_id,
                mandate_version=mandate.version,
                rule_fired="policy.evaluate_quote",
            )
        )

        offer_id = await self._ops.record_offer(
            OfferRow(
                rfq_id=rfq_id,
                counterparty_id=proposal.carrier_id,
                call_sid=proposal.source_call_id,
                quoted_currency=_quoted_currency(proposal),
                is_total_final=proposal.cost_is_final,
                evidence_offset_ms=proposal.transcript_anchor_ms,
                policy_amount_usd_minor=(
                    usd_to_minor(decision.cost.buffered_usd) if decision.cost else None
                ),
                mandate_id=mandate.mandate_id,
                pickup_window_start=proposal.pickup_at,
                pickup_window_end=proposal.pickup_at,
            )
        )

        if decision.outcome is not PolicyOutcome.ALLOW:
            bound.info("proposal_not_authorized")
            return SettlementResult(decision=decision, decision_id=decision_id, offer_id=offer_id)

        # ALLOW implies require_preagreement_evidence passed, so the anchor is present.
        # Asserting it keeps the invariant local instead of trusting a caller three layers up.
        anchor = proposal.transcript_anchor_ms
        if anchor is None:  # pragma: no cover - unreachable while ALLOW implies an anchor
            raise AssertionError("ALLOW without an audio anchor")

        commitment_id = await self._ops.open_commitment(
            operation_id=mandate.operation_id,
            offer_id=offer_id,
            participant_segment_id=participant_segment_id,
            audio_offset_ms=anchor,
            decision_id=decision_id,
        )
        try:
            await self._ops.accept_offer(offer_id)
        except Exception as exc:
            # Another carrier was awarded this RFQ first. Two dispatchers confirming at the
            # same moment is a real race when three lines are open at once, and the loser
            # must end as a recorded non-commitment rather than an exception nobody sees.
            # Deliberately before the recap: never tell a carrier they have the load when
            # someone else already does.
            await self._ops.transition(
                commitment_id,
                to_state=ChainState.NOT_COMMITTED,
                reason=f"award lost: {exc}",
                decision_id=decision_id,
            )
            bound.warning("award_race_lost", commitment_id=commitment_id)
            return SettlementResult(
                decision=decision,
                decision_id=decision_id,
                offer_id=offer_id,
                commitment_id=commitment_id,
                state=ChainState.NOT_COMMITTED,
            )

        delivery = await self._sender.send(recap, self._recap_to)
        if delivery.status is not RecapDeliveryStatus.SENT:
            await self._ops.transition(
                commitment_id,
                to_state=ChainState.RECAP_FAILED,
                reason=delivery.error or "recap delivery failed",
                decision_id=decision_id,
            )
            bound.warning("recap_failed_commitment_not_counted", commitment_id=commitment_id)
            return SettlementResult(
                decision=decision,
                decision_id=decision_id,
                offer_id=offer_id,
                commitment_id=commitment_id,
                state=ChainState.RECAP_FAILED,
            )

        # Two writes, not one. The chain has to show that the recap went out *before* the
        # commitment counted; collapsing them would lose the ordering the brief asks for.
        await self._ops.transition(
            commitment_id,
            to_state=ChainState.RECAP_SENT,
            reason=f"recap delivered to {self._recap_to}",
            decision_id=decision_id,
        )
        await self._ops.transition(
            commitment_id,
            to_state=ChainState.COMMITTED,
            reason="verbal agreement and written recap both verified",
            decision_id=decision_id,
        )
        bound.info("commitment_committed", commitment_id=commitment_id)
        return SettlementResult(
            decision=decision,
            decision_id=decision_id,
            offer_id=offer_id,
            commitment_id=commitment_id,
            state=ChainState.COMMITTED,
        )


def _verdict(outcome: PolicyOutcome) -> str:
    """Map the policy vocabulary onto the database's, which also allows 'clarify'."""

    return {
        PolicyOutcome.ALLOW: "allow",
        PolicyOutcome.DENY: "deny",
        PolicyOutcome.ESCALATE: "escalate",
    }[outcome]


def _quoted_currency(proposal: QuoteProposal) -> str:
    """The currency the carrier actually spoke.

    A proposal may carry components in more than one currency; the column records what was
    quoted, and the USD figure beside it records what policy made of it. When the
    components disagree, USD is the honest answer because no single spoken currency covers
    the total.
    """

    currencies = {component.currency for component in proposal.components}
    return currencies.pop() if len(currencies) == 1 else "USD"

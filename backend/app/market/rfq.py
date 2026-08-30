"""One RFQ across N carriers, and exactly one award.

This package owns AGENTS.md invariant #5, which is really two rules that only work
together:

    RFQ and AWARD are separate phases.   Three carriers may hold confirmed offers at the
                                         same time — that is the point of asking three.
    Only one award may run.              And only in AWARDING, which locks the market so
                                         a late offer cannot change what was already
                                         decided.

Two open bookings is the worst outcome this system can produce: two trucks arrive, the
client pays twice, and the agent cannot explain which promise was real. So the award path
is deliberately narrow and refuses by default.

The dialling is injected rather than imported. ``market/`` may not import ``telephony/``
— it sits below it in the layering — and that turns out to be the right shape anyway: the
phase rules and the ranking are pure and testable with no phone anywhere near them.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

import structlog

from app.domain import (
    FxSnapshot,
    Mandate,
    PolicyDecision,
    PolicyOutcome,
    QuoteProposal,
    ReasonCode,
)
from app.policy import evaluate_quote, require_preagreement_evidence, select_best

log = structlog.get_logger(__name__)

#: Placing one outbound call. Returns the provider's call id. Injected by the composition
#: root so this package never learns what Twilio is.
Dial = Callable[[str], Awaitable[str]]


class RfqPhase(StrEnum):
    OPEN = "open"
    AWARDING = "awarding"
    CLOSED = "closed"


@dataclass(frozen=True)
class Participant:
    """One carrier invited to quote, and the number that was actually dialled."""

    counterparty_id: str
    phone: str
    call_id: str | None = None


@dataclass(frozen=True)
class Ranked:
    """One carrier's offer as the human will read it afterwards.

    ``rank`` is None when the offer was not eligible. The decision travels with it, so the
    comparison explains itself: "not chosen because OUTSIDE_MANDATE" is a different fact
    from "not chosen because someone else was cheaper", and the table has to say which.
    """

    proposal: QuoteProposal
    decision: PolicyDecision
    rank: int | None

    @property
    def eligible(self) -> bool:
        return self.decision.outcome is PolicyOutcome.ALLOW


@dataclass(frozen=True)
class Award:
    """The outcome of one awarding round. ``winner`` is None when nothing was eligible."""

    winner: QuoteProposal | None
    reason: ReasonCode
    comparison: tuple[Ranked, ...]

    @property
    def awarded(self) -> bool:
        return self.winner is not None


class MarketError(RuntimeError):
    """A phase rule was violated. Always a refusal, never a correction."""


@dataclass
class Rfq:
    """The market for one operation. Not reusable — a new round is a new RFQ."""

    rfq_id: str
    operation_id: str
    participants: dict[str, Participant] = field(default_factory=dict)
    #: Carrier id -> why they are out. Kept rather than deleted: "three called, one
    #: refused the lane" is part of the auditable story of how the winner was chosen.
    unavailable: dict[str, str] = field(default_factory=dict)
    phase: RfqPhase = RfqPhase.OPEN
    _offers: dict[str, QuoteProposal] = field(default_factory=dict, repr=False)

    # --- inviting and dialling ------------------------------------------------------

    def invite(self, counterparty_id: str, phone: str) -> None:
        if self.phase is not RfqPhase.OPEN:
            raise MarketError(f"cannot invite in phase {self.phase}")
        self.participants[counterparty_id] = Participant(counterparty_id, phone)

    async def dial_all(self, dial: Dial) -> dict[str, str | None]:
        """Call every invited carrier at once. Returns call id per carrier, None if it failed.

        Concurrent because serial dialling is the thing being replaced: a human coordinator
        calls three carriers one after another and the demurrage clock runs the whole time.

        One carrier not answering is not a failed RFQ — it is an RFQ with two participants.
        So failures are returned, never raised.
        """
        if self.phase is not RfqPhase.OPEN:
            raise MarketError(f"cannot dial in phase {self.phase}")

        async def _one(participant: Participant) -> tuple[str, str | None]:
            try:
                return participant.counterparty_id, await dial(participant.phone)
            except Exception:
                log.exception("rfq_dial_failed", carrier_id=participant.counterparty_id)
                return participant.counterparty_id, None

        results = dict(await asyncio.gather(*(_one(p) for p in self.participants.values())))
        for counterparty_id, call_id in results.items():
            if call_id is not None:
                existing = self.participants[counterparty_id]
                self.participants[counterparty_id] = Participant(
                    existing.counterparty_id, existing.phone, call_id
                )
        log.info(
            "rfq_dialled",
            rfq_id=self.rfq_id,
            reached=sum(1 for c in results.values() if c),
            invited=len(results),
        )
        return results

    # --- collecting offers ----------------------------------------------------------

    def record_offer(self, proposal: QuoteProposal) -> None:
        """Hold one carrier's current offer.

        Late offers are refused rather than quietly ignored: once AWARDING has begun, a new
        number arriving from a fourth phone call must not be able to change a decision the
        human is already looking at.
        """
        if self.phase is not RfqPhase.OPEN:
            raise MarketError(f"the market is {self.phase}; offers are no longer accepted")
        if proposal.operation_id != self.operation_id:
            raise MarketError("proposal belongs to a different operation")
        if proposal.carrier_id in self.unavailable:
            raise MarketError(f"{proposal.carrier_id} is marked unavailable for this RFQ")
        # A carrier improving its own quote replaces its own entry and nobody else's. The
        # superseded number is not lost — ledger/ and offers/ keep every one of them; this
        # dict only answers "what does each carrier stand behind right now".
        self._offers[proposal.carrier_id] = proposal

    @property
    def offers(self) -> tuple[QuoteProposal, ...]:
        return tuple(self._offers.values())

    def mark_unavailable(self, counterparty_id: str, reason: str) -> None:
        """A carrier is out: "we don't serve that lane", or nobody ever answered.

        Their offer, if any, stops being a candidate — but the RFQ carries on with whoever
        is left. A refusal is an ordinary outcome of asking three carriers, not a failure
        of the round, and treating it as one would make the agent give up the moment the
        first dispatcher said no.
        """
        if self.phase is RfqPhase.CLOSED:
            raise MarketError("the market is closed")
        self._offers.pop(counterparty_id, None)
        self.unavailable[counterparty_id] = reason
        log.info(
            "carrier_unavailable",
            rfq_id=self.rfq_id,
            carrier_id=counterparty_id,
            reason=reason,
            remaining=len(self._offers),
        )

    # --- awarding -------------------------------------------------------------------

    def begin_awarding(self) -> None:
        """Lock the market. Idempotent, because the trigger may arrive twice."""
        if self.phase is RfqPhase.CLOSED:
            raise MarketError("the market is closed")
        self.phase = RfqPhase.AWARDING

    def compare(
        self, mandate: Mandate, fx: Mapping[str, FxSnapshot], *, now: datetime
    ) -> tuple[Ranked, ...]:
        """Every offer, judged, ordered — the table the human audits afterwards.

        Readable in any phase and free of side effects: the operator watching three live
        calls needs to see the standings before deciding to award, not after.
        """
        judged = [
            (
                proposal,
                require_preagreement_evidence(
                    mandate, proposal, evaluate_quote(mandate, proposal, fx, now=now)
                ),
            )
            for proposal in self._offers.values()
        ]
        # Ranking uses exactly the same ordering the award does, so the table can never
        # disagree with the outcome.
        order = {
            proposal.proposal_id: index for index, proposal in enumerate(_eligible_in_order(judged))
        }
        ranked = [
            Ranked(proposal, decision, order.get(proposal.proposal_id))
            for proposal, decision in judged
        ]
        return tuple(
            sorted(ranked, key=lambda r: (r.rank is None, r.rank or 0, r.proposal.proposal_id))
        )

    def award(self, mandate: Mandate, fx: Mapping[str, FxSnapshot], *, now: datetime) -> Award:
        """Pick the winner. Once, in AWARDING, or not at all."""
        # One guard, not two. Awarding closes the market, and nothing reopens it, so
        # "only one award may ever run" is the phase machine rather than a second flag
        # that could disagree with it.
        if self.phase is not RfqPhase.AWARDING:
            raise MarketError(f"award may only run in AWARDING, not {self.phase}")

        comparison = self.compare(mandate, fx, now=now)
        winner = select_best([(r.proposal, r.decision) for r in comparison if r.eligible])
        # Closing even when nothing was eligible is deliberate. An RFQ that stays open
        # after a failed award is an RFQ someone will award twice.
        self.phase = RfqPhase.CLOSED
        reason = ReasonCode.ALLOWED if winner else ReasonCode.NO_ELIGIBLE_CANDIDATE
        log.info(
            "rfq_awarded",
            rfq_id=self.rfq_id,
            winner=winner.carrier_id if winner else None,
            considered=len(comparison),
            reason=reason.value,
        )
        return Award(winner=winner, reason=reason, comparison=comparison)


def _eligible_in_order(
    judged: list[tuple[QuoteProposal, PolicyDecision]],
) -> list[QuoteProposal]:
    """Repeatedly ask policy for the best remaining one.

    Ranking is delegated rather than reimplemented: ``select_best`` owns the tie-breaks,
    and a second ordering here would eventually disagree with the one that actually awards.
    """
    remaining = [(p, d) for p, d in judged if d.outcome is PolicyOutcome.ALLOW]
    ordered: list[QuoteProposal] = []
    while remaining:
        best = select_best(remaining)
        if best is None:
            break
        ordered.append(best)
        remaining = [(p, d) for p, d in remaining if p.proposal_id != best.proposal_id]
    return ordered

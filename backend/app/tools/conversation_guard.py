"""Deterministic conversational mediation exposed through the tools boundary."""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from app.domain import CommitmentMode, CostComponent, Mandate, PolicyOutcome, QuoteProposal
from app.policy import evaluate_quote

ESCALATION_RESPONSE = (
    "That exceeds my authority. I cannot accept or commit; I will escalate it to my team."
)
NON_BINDING_RESPONSE = "I can record that only as a non-binding pre-agreement for policy review."

_USD_AMOUNT = re.compile(
    r"(?ix)(?:\$\s*(?P<prefix>\d[\d,]*(?:\.\d{1,2})?)|"
    r"(?P<suffix>\d[\d,]*(?:\.\d{1,2})?)\s*(?:USD|US\s+dollars?|dollars?))"
)
_AUTHORITY_CLAIM = re.compile(
    r"(?i)\b(?:i|we)\s+(?:accept|agree|confirm|commit|book)|"
    r"\b(?:it is|that's|that is)\s+(?:booked|confirmed|agreed)|\bwe have a deal\b"
)


class ConversationGuard:
    """A deliberately narrow demo adapter; it can deny, never authorize a commitment."""

    def __init__(self, mandate: Mandate) -> None:
        self._mandate = mandate

    def input_directive(self, text: str, *, call_id: str, offset_ms: int) -> str | None:
        """Immediately escalate any explicit USD amount that policy evaluates over cap."""
        for match in _USD_AMOUNT.finditer(text):
            raw = (match.group("prefix") or match.group("suffix")).replace(",", "")
            try:
                amount = Decimal(raw)
            except InvalidOperation:
                continue
            now = datetime.now(UTC)
            proposal = QuoteProposal(
                proposal_id=f"spoken:{call_id}:{offset_ms}:{match.start()}",
                operation_id=self._mandate.operation_id,
                carrier_id="unverified-conversation-counterparty",
                carrier_contact_id="unverified-conversation-contact",
                components=(CostComponent(name="stated-all-in", amount=amount, currency="USD"),),
                cost_is_final=True,
                pickup_at=self._mandate.pickup_not_before,
                equipment=next(iter(sorted(self._mandate.allowed_equipment))),
                valid_until=now + timedelta(minutes=5),
                source_call_id=call_id,
                source_event_id=f"heard:{call_id}:{offset_ms}:{match.start()}",
                transcript_anchor_ms=offset_ms,
            )
            if (
                evaluate_quote(self._mandate, proposal, {}, now=now).outcome
                is not PolicyOutcome.ALLOW
            ):
                return ESCALATION_RESPONSE
        return None

    def filter_model_chunk(self, text: str) -> tuple[str, bool]:
        """Block spoken claims of authority; calls can only describe a pre-agreement."""
        if _AUTHORITY_CLAIM.search(text):
            return NON_BINDING_RESPONSE, True
        return text, False


def build_demo_guard() -> ConversationGuard:
    return ConversationGuard(
        Mandate(
            mandate_id="DEMO-MANDATE",
            version=1,
            owner_id="demo-owner",
            operation_id="OP-1042",
            max_all_in_usd=Decimal("9000"),
            pickup_not_before=datetime(2026, 9, 2, tzinfo=UTC),
            pickup_not_after=datetime(2026, 9, 4, 23, 59, tzinfo=UTC),
            allowed_equipment=frozenset({"40-foot container chassis"}),
            commitment_mode=CommitmentMode.HUMAN_ESCALATION,
        )
    )

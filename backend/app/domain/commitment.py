"""The commitment chain: the states a commitment passes through, and the rows behind them.

Types only, like the rest of ``domain/``. The transitions themselves are decided in
``policy/`` and written by ``repo/``; nothing here decides anything.

The chain exists because "committed" is not a boolean. A verbal yes on a call, a recap the
counterparty has actually received, and a truck that showed up are three different facts,
and the demo has to be able to show which of them is true right now (AGENTS.md invariant
#3). The last three states arrive hours later, outside the call that created the
commitment.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ChainState(StrEnum):
    """Mirrors the ``commitments.chain_state`` check constraint, deliberately.

    Two spellings of the same enum would drift, and the database is the one that fails
    closed, so this list follows it rather than the other way around.
    """

    VERBAL = "VERBAL"
    RECAP_SENT = "RECAP_SENT"
    COMMITTED = "COMMITTED"
    RESOURCED = "RESOURCED"
    DOCUMENTED = "DOCUMENTED"
    EXECUTED = "EXECUTED"
    # Terminal failures. A commitment that reaches either of these never counted, and the
    # interface must never render it as firm.
    RECAP_FAILED = "RECAP_FAILED"
    NOT_COMMITTED = "NOT_COMMITTED"
    SUPERSEDED = "SUPERSEDED"


#: The states in which a commitment may be shown to a human as real. Everything else is
#: amber at best. Kept as data rather than an ``if`` so the dashboard and the tests agree.
SETTLED_STATES = frozenset(
    {ChainState.COMMITTED, ChainState.RESOURCED, ChainState.DOCUMENTED, ChainState.EXECUTED}
)


class OfferRow(BaseModel):
    """One priced offer as it was said, plus what policy later made of it.

    An offer that changes is a new row, never an edit (invariant #4): the trial by fire is
    a counterparty agreeing to a price and then changing it, and last-write-wins would
    destroy the very fact being tested.
    """

    model_config = ConfigDict(frozen=True)

    rfq_id: str
    counterparty_id: str
    call_sid: str | None = None
    quoted_currency: str = Field(min_length=3, max_length=3)
    is_total_final: bool = False
    evidence_offset_ms: int | None = Field(default=None, ge=0)
    # Written by policy/, in Decimal, then stored as USD minor units. None until evaluated.
    policy_amount_usd_minor: int | None = Field(default=None, ge=0)
    fx_snapshot_id: str | None = None
    mandate_id: str | None = None
    pickup_window_start: datetime | None = None
    pickup_window_end: datetime | None = None


class DecisionRow(BaseModel):
    """One evaluation, including the denials.

    The denials are the interesting rows during the trial by fire: they are the only way to
    *show* a refusal instead of asserting one.
    """

    model_config = ConfigDict(frozen=True)

    operation_id: str
    verdict: str
    reason_code: str
    proposal: dict[str, object]
    call_sid: str | None = None
    mandate_id: str | None = None
    mandate_version: int | None = None
    fx_snapshot_id: str | None = None
    rule_fired: str | None = None


def usd_to_minor(amount: Decimal) -> int:
    """Money crosses this boundary as minor units, never as a float.

    ``Decimal`` is what ``policy/`` computes in; the column is a ``bigint``. Rounding is
    not specified here because policy has already quantized to cents — a value that still
    needs rounding at this point is a bug upstream, and int() would hide it.
    """

    minor = amount.scaleb(2)
    if minor != minor.to_integral_value():
        raise ValueError(f"amount {amount} is not a whole number of cents")
    return int(minor)

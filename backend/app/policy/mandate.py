"""The price cap, as an `if` statement.

Deliberately the narrowest rule that makes a bound mandate load-bearing: given the
mandate this call is running under and an all-in cost already expressed in USD, say
whether the number is inside the authorization or has to go to a person.

It is not the reference monitor. The full one — window, equipment, FX snapshots, cost
completeness, evidence — is being reviewed in the case-spine pull request as
`policy/engine.py:evaluate_quote`. When that merges, delete this module and call it: it
subsumes this rule exactly. Until then this exists so that "the session is bound to a
mandate" is a claim with teeth rather than a field nobody reads.

Currency conversion is deliberately absent. Invariant #9 requires an approved immutable
FX snapshot for every non-USD component, and inventing a rate here to make a comparison
work would be precisely the failure that invariant exists to prevent. Callers hand this
function USD or they do not call it.
"""

from decimal import Decimal

from app.domain.models import HandoffReason
from app.domain.security import Mandate


def quote_escalation_reason(mandate: Mandate, all_in_usd: Decimal) -> HandoffReason | None:
    """`None` means the quote sits inside the mandate. Anything else must escalate.

    The comparison is on the mandate the *call* is bound to, never on a figure the
    counterparty supplied and never on a plausibility judgement (invariant #2). A caller
    saying the ceiling is higher does not move it; it only changes which mandate they
    would need, and they cannot choose that from inside the call.
    """
    if all_in_usd > mandate.max_all_in_usd:
        return HandoffReason.OUTSIDE_MANDATE
    return None

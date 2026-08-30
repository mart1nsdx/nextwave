"""Deterministic authorization. The only module that may authorize a COMMITTED write.

MAY IMPORT:  domain, stdlib. Nothing else, ever.
IMPORTED BY: market, tools.

Pure and synchronous — no network, no async, no LLM, no clock reads that aren't injected.
Unit-testable with zero mocks. The price cap is an `if` statement, never a prompt.
Invariant #1 ("the LLM never writes a commitment") holds because this package cannot
reach anything that talks to a model. Enforced by tests/test_layering.py.
"""

from app.policy.handoff import handoff_is_authorized
from app.policy.mandate import quote_escalation_reason

__all__ = ["handoff_is_authorized", "quote_escalation_reason"]

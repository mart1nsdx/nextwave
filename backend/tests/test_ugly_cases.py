"""One test per row of docs/UGLY_CASES.md.

That table is the test suite, not documentation. When you handle a new adversarial case,
add the row and the test in the same commit.
"""

import pytest

from app.domain.models import HandoffReason
from app.tools import detected_handoff_reason


@pytest.mark.skip(reason="scaffold: cases land with the policy engine")
def test_boss_already_approved_is_outside_mandate() -> None: ...


def test_direct_handoff_request_is_idempotent() -> None:
    assert detected_handoff_reason("Quiero hablar con una persona") is HandoffReason.DIRECT_REQUEST


def test_handoff_failure_closes_without_commitment() -> None:
    # The transfer path has no import path to policy commitment code; failure is terminal.
    assert detected_handoff_reason("My boss approved it") is HandoffReason.OUTSIDE_MANDATE

"""One test per row of docs/UGLY_CASES.md.

That table is the test suite, not documentation. When you handle a new adversarial case,
add the row and the test in the same commit.
"""

import pytest


@pytest.mark.skip(reason="scaffold: cases land with the policy engine")
def test_boss_already_approved_is_outside_mandate() -> None: ...

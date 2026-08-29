"""Policy engine unit tests. Pure — no network, no mocks, no audio.

Policy and state-machine changes require a test here (AGENTS.md). The price cap is an
`if` statement, so it is testable as one.
"""

import pytest


@pytest.mark.skip(reason="scaffold: policy engine lands in the next task")
def test_price_above_cap() -> None: ...

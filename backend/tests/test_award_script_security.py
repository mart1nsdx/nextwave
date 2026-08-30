"""The recap-ranking script cannot bypass deterministic authorization."""

import pytest

from scripts.award_from_recaps import do_writes, mutation_block_reason


def test_every_mutating_cli_mode_fails_closed() -> None:
    assert mutation_block_reason(commit=False, sms=False, force_incomplete=False) is None
    assert "--commit is disabled" in (
        mutation_block_reason(commit=True, sms=False, force_incomplete=False) or ""
    )
    assert "--sms is disabled" in (
        mutation_block_reason(commit=False, sms=True, force_incomplete=False) or ""
    )
    assert "--force-incomplete is disabled" in (
        mutation_block_reason(commit=False, sms=False, force_incomplete=True) or ""
    )


def test_internal_write_helper_cannot_be_called_with_commit() -> None:
    with pytest.raises(RuntimeError, match="unsafe write blocked"):
        do_writes(
            object(),
            tenant_id="tenant",
            operation_id="operation",
            rfq_id="rfq",
            mandate_id="mandate",
            carriers=[],
            winner=object(),  # type: ignore[arg-type]
            reason="model-ranked candidate",
            fx={},
            commit=True,
        )

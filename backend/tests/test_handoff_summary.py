"""The live handoff briefing is model-produced context, never an authorization."""

from app.agent.recap import build_handoff_summary
from app.domain.models import HandoffReason, HandoffRequest


class FakeHandoffSummaryModel:
    async def handoff_summary(self, request: HandoffRequest, transcript: str) -> str:
        assert request.reason is HandoffReason.DIRECT_REQUEST
        assert "nueve mil pesos" in transcript
        return "El carrier pidió hablar con una persona tras cotizar nueve mil pesos."


async def test_handoff_summary_uses_evidence_without_authorizing() -> None:
    request = HandoffRequest.model_validate(
        {
            "handoff_id": "12345678-1234-1234-1234-123456789012",
            "call_sid": "CAhandoff",
            "reason": "direct_request",
            "evidence_offset_ms": 120,
            "note": "caller asked for a person",
        }
    )
    summary = await build_handoff_summary(
        request,
        "[120 ms] caller: cotizo nueve mil pesos y quiero hablar con una persona",
        FakeHandoffSummaryModel(),  # type: ignore[arg-type]
    )

    assert "nueve mil pesos" in summary

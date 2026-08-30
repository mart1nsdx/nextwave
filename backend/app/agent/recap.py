"""Post-call analysis: turn a transcript into a recap and a structured brief.

Pure orchestration over an injected RecapModel. No I/O, no vendor SDK here — the model
seam is domain.RecapModel, so this stays testable with a fake.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.domain.models import CallBrief, HandoffRequest, Recap, RecapContext
from app.domain.ports import RecapModel


async def build_recap(
    call_sid: str,
    transcript: str,
    model: RecapModel,
    *,
    context: RecapContext | None = None,
) -> Recap:
    recap = await model.summarize(transcript, context or RecapContext())
    return recap.model_copy(update={"call_sid": call_sid, "generated_at": datetime.now(UTC)})


async def build_brief(call_sid: str, transcript: str, model: RecapModel) -> CallBrief:
    brief = await model.brief(transcript)
    return brief.model_copy(update={"call_sid": call_sid, "generated_at": datetime.now(UTC)})


async def build_handoff_summary(
    request: HandoffRequest, transcript: str, model: RecapModel
) -> str:
    """Ask the model for context only; the result cannot authorize the transfer."""

    return await model.handoff_summary(request, transcript)

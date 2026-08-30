"""Concrete RecapModel backed by OpenAI structured outputs.

All post-call processing runs on OpenAI (hackathon credits + API budget). This is a
plain chat-completions call with a JSON schema response — not the Realtime API.

MAY IMPORT: domain, stdlib, openai. Not app.config — the API key is passed in by the
composition root so this package keeps its single allowed dependency (domain).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agent.prompts import BRIEF_SYSTEM, RECAP_SYSTEM, RECAP_USER_TEMPLATE
from app.domain.models import (
    AgreementCandidate,
    BriefAction,
    BriefMention,
    CallBrief,
    Recap,
    RecapContext,
)


class _RecapDraft(BaseModel):
    """Model output shape — no call_sid, no timestamp; the caller stamps those."""

    summary: str
    key_points: list[str] = Field(default_factory=list)
    quoted_prices: list[str] = Field(default_factory=list)
    names: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    objections: list[str] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)
    agreement_candidates: list[AgreementCandidate] = Field(default_factory=list)


class _BriefDraft(BaseModel):
    actions: list[BriefAction] = Field(default_factory=list)
    mentions: list[BriefMention] = Field(default_factory=list)


def _context_block(context: RecapContext) -> str:
    lines: list[str] = []
    if context.operation_ref:
        lines.append(f"Operation: {context.operation_ref}")
    if context.mandate_summary:
        lines.append(f"Mandate (for reference only): {context.mandate_summary}")
    if context.carriers:
        lines.append(f"Carriers in play: {', '.join(context.carriers)}")
    return ("\n".join(lines) + "\n\n") if lines else ""


class OpenAIRecapModel:
    """Implements domain.RecapModel."""

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._client_obj: object | None = None

    @property
    def name(self) -> str:
        return self._model

    @property
    def _client(self) -> Any:
        if self._client_obj is None:
            if not self._api_key:
                raise RuntimeError("OPENAI_API_KEY must be set for recap generation")
            from openai import AsyncOpenAI

            self._client_obj = AsyncOpenAI(api_key=self._api_key)
        return self._client_obj

    async def summarize(self, transcript: str, context: RecapContext) -> Recap:
        user = RECAP_USER_TEMPLATE.format(
            context_block=_context_block(context), transcript=transcript
        )
        completion = await self._client.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": RECAP_SYSTEM},
                {"role": "user", "content": user},
            ],
            response_format=_RecapDraft,
        )
        draft = completion.choices[0].message.parsed
        if draft is None:
            raise RuntimeError("recap model returned no parsed content")
        return Recap(call_sid="", model=self._model, **draft.model_dump())

    async def brief(self, transcript: str) -> CallBrief:
        completion = await self._client.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": BRIEF_SYSTEM},
                {"role": "user", "content": transcript},
            ],
            response_format=_BriefDraft,
        )
        draft = completion.choices[0].message.parsed
        if draft is None:
            raise RuntimeError("brief model returned no parsed content")
        return CallBrief(call_sid="", model=self._model, **draft.model_dump())

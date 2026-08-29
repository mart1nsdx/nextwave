"""Prompts, negotiation guidance, and proposal extraction from speech.

MAY IMPORT:  domain.
IMPORTED BY: realtime.

Content, not logic. This package shapes what the agent *says*; policy/ decides what it
may *do*. Authorization logic in a prompt here is a bug — prompts are untrusted the
moment a counterparty starts talking, which is exactly why they live outside policy/.

Post-call analysis (recap, brief) lives here too: it is content extraction over a
transcript, and its output is evidence a policy step reads — never authority.
"""

from app.agent.models import OpenAIRecapModel
from app.agent.recap import build_brief, build_recap

__all__ = ["OpenAIRecapModel", "build_brief", "build_recap"]

"""Prompts, negotiation guidance, and proposal extraction from speech.

MAY IMPORT:  domain.
IMPORTED BY: voice.

Content, not logic. This package shapes what the agent *says*; policy/ decides what it
may *do*. Authorization logic in a prompt here is a bug — prompts are untrusted the
moment a counterparty starts talking, which is exactly why they live outside policy/.
"""

from typing import Any

from agents import Agent, ModelSettings, OpenAIResponsesModel, set_tracing_disabled
from openai import AsyncOpenAI
from openai.types.shared import Reasoning

from .models import OpenAIRecapModel
from .prompts import GREETING, RECOVERY_LINE, SYSTEM_PROMPT
from .recap import build_brief, build_recap

__all__ = [
    "GREETING",
    "RECOVERY_LINE",
    "SYSTEM_PROMPT",
    "OpenAIRecapModel",
    "build_agent",
    "build_brief",
    "build_recap",
]


def build_agent(model: str, api_key: str, tools: list[Any] | None = None) -> Agent:
    """The conversational agent. `tools` is empty today and stays a parameter on purpose.

    The model id and key arrive as arguments rather than being read here because this
    package cannot import config — it sits below it in the layering. voice/ passes them in.

    The client is constructed explicitly rather than left to the SDK's environment lookup.
    Settings are loaded from .env into a Settings object and never exported to os.environ,
    so a key that is present in .env is invisible to any library that reads the
    environment itself — which fails only once a real call reaches the model.

    When tools/ lands, every one of them is a `propose_*` that ends at policy.evaluate().
    Nothing handed to this function may commit anything on its own (invariant #1).
    """
    if not model:
        raise ValueError("OPENAI_AGENT_MODEL is empty — verify the current model id and set it.")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is empty — the agent would have nothing to think with.")
    # The SDK uploads traces — including what was said on the call — to OpenAI's tracing
    # backend by default. These are real conversations with real counterparties, and
    # AGENTS.md already forbids putting raw transcripts where they do not belong. Turning
    # it on later is a deliberate decision, not the default.
    set_tracing_disabled(True)
    return Agent(
        name="Volta",
        instructions=SYSTEM_PROMPT,
        model=OpenAIResponsesModel(model=model, openai_client=AsyncOpenAI(api_key=api_key)),
        # Tuned for a phone call, where latency is the product. A reasoning model left at
        # its defaults spends seconds thinking, and seconds of silence on a call read as a
        # dropped line — the dispatcher says "bueno?" and hangs up. Short answers are also
        # simply correct here: nobody monologues at a dispatcher.
        model_settings=ModelSettings(
            reasoning=Reasoning(effort="minimal"),
            verbosity="low",
            max_tokens=300,
            # A hung request must not become open-ended dead air. The turn fails, the
            # agent says RECOVERY_LINE and hands the turn back.
            timeout=12.0,
        ),
        tools=tools or [],
    )

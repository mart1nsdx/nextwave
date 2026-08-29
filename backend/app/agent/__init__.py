"""Prompts, negotiation guidance, and proposal extraction from speech.

MAY IMPORT:  domain.
IMPORTED BY: voice.

Content, not logic. This package shapes what the agent *says*; policy/ decides what it
may *do*. Authorization logic in a prompt here is a bug — prompts are untrusted the
moment a counterparty starts talking, which is exactly why they live outside policy/.
"""

from typing import Any

from agents import Agent

from .prompts import GREETING, SYSTEM_PROMPT

__all__ = ["GREETING", "SYSTEM_PROMPT", "build_agent"]


def build_agent(model: str, tools: list[Any] | None = None) -> Agent:
    """The conversational agent. `tools` is empty today and stays a parameter on purpose.

    The model id arrives as an argument rather than being read here because this package
    cannot import config — it sits below it in the layering. voice/ passes it in.

    When tools/ lands, every one of them is a `propose_*` that ends at policy.evaluate().
    Nothing handed to this function may commit anything on its own (invariant #1).
    """
    if not model:
        raise ValueError("OPENAI_AGENT_MODEL is empty — verify the current model id and set it.")
    return Agent(name="Volta", instructions=SYSTEM_PROMPT, model=model, tools=tools or [])

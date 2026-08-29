"""Prompts, negotiation guidance, and proposal extraction from speech.

MAY IMPORT:  domain.
IMPORTED BY: voice.

Content, not logic. This package shapes what the agent *says*; policy/ decides what it
may *do*. Authorization logic in a prompt here is a bug — prompts are untrusted the
moment a counterparty starts talking, which is exactly why they live outside policy/.
"""

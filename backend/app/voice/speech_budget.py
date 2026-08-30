"""Deterministic spoken-duration estimates for conversational turn budgeting."""

import re

WORDS_PER_MINUTE = 150
ORDINARY_MAX_WORDS = 18
ORDINARY_TARGET_MS = 6000


def spoken_word_count(text: str) -> int:
    return len(re.findall(r"\b[\wÀ-ÿ]+(?:[-'][\wÀ-ÿ]+)?\b", text, flags=re.UNICODE))


def estimated_spoken_ms(text: str) -> int:
    """Language-neutral planning estimate; real TTS/PSTN evidence remains authoritative."""
    return round(spoken_word_count(text) * 60_000 / WORDS_PER_MINUTE)


def ordinary_turn_over_budget(text: str) -> bool:
    return spoken_word_count(text) > ORDINARY_MAX_WORDS

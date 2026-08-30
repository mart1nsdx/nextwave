"""Deterministic duration-budget oracle; it warns but never truncates material terms."""

from app.voice.speech_budget import (
    ORDINARY_MAX_WORDS,
    estimated_spoken_ms,
    ordinary_turn_over_budget,
    spoken_word_count,
)


def test_short_spanish_turn_fits_six_second_budget() -> None:
    text = "Del 2 al 4 de septiembre. ¿Tiene chasis de 40 pies?"
    assert spoken_word_count(text) <= ORDINARY_MAX_WORDS
    assert estimated_spoken_ms(text) <= 6000
    assert not ordinary_turn_over_budget(text)


def test_long_turn_is_flagged_without_mutating_it() -> None:
    text = " ".join(f"palabra{index}" for index in range(19))
    assert ordinary_turn_over_budget(text)
    assert text.endswith("palabra18")

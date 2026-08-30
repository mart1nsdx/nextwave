"""Fast speech starts at short natural clauses rather than after a whole paragraph."""

from app.voice.llm import _take_chunk


def test_short_sentence_is_emitted_immediately() -> None:
    assert _take_chunk("Sí, lo reviso.") == ("Sí, lo reviso.", "")


def test_unpunctuated_model_output_is_bounded_for_tts() -> None:
    text = "palabra " * 20
    chunk = _take_chunk(text)
    assert chunk is not None
    emitted, remainder = chunk
    assert len(emitted) <= 96
    assert emitted and remainder

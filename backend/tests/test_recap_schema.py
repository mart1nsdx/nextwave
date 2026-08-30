"""The recap response schema, as a test.

`agent/models.py` hands `_RecapDraft` to OpenAI as a structured-output response format,
so the *schema* is the only vocabulary the extractor has. A required, non-nullable
integer anchor leaves the model no way to say "nothing in this call anchors that yes" —
it must emit some number, and a number it did not hear is a fabrication (AGENTS.md
invariant #8). These tests pin the shape that keeps "I don't know" expressible.
"""

from openai.lib._pydantic import to_strict_json_schema

from app.agent.models import _RecapDraft


def _agreement_candidate_schema() -> dict[str, object]:
    return to_strict_json_schema(_RecapDraft)["$defs"]["AgreementCandidate"]


def test_agreement_candidate_schema_permits_null_anchor() -> None:
    """The serialised schema — not the Python annotation — must accept a null anchor."""
    anchor = _agreement_candidate_schema()["properties"]["audio_offset_ms"]  # type: ignore[index]
    variants = {tuple(sorted(v.items())) for v in anchor["anyOf"]}  # type: ignore[index]
    assert ("type", "null") in {item for variant in variants for item in variant}, (
        f"audio_offset_ms cannot express 'no anchor': {anchor}"
    )


def test_agreement_candidate_anchor_stays_required_in_the_schema() -> None:
    """Strict structured outputs list every property as required; null is the escape hatch.

    Asserted so a future switch to a truly optional field is a deliberate change: dropping
    the key from `required` would let the model omit the anchor silently instead of
    stating that it has none.
    """
    schema = _agreement_candidate_schema()
    assert "audio_offset_ms" in schema["required"]  # type: ignore[operator]

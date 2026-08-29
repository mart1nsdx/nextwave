"""The personality may shape conversation but must describe authority truthfully."""

from app.agent import DEMO_CONTEXT, DEMO_PROFILE, CallPhase, build_system_prompt


def test_rfq_prompt_calls_the_phone_result_non_binding() -> None:
    prompt = build_system_prompt(DEMO_PROFILE, DEMO_CONTEXT)
    assert "non-binding pre-agreement" in prompt
    assert "You cannot choose that path and you cannot send that email" in prompt


def test_award_personality_confirms_terms_without_claiming_booking_authority() -> None:
    context = DEMO_CONTEXT.model_copy(update={"phase": CallPhase.AWARD})
    prompt = build_system_prompt(DEMO_PROFILE, context)
    assert "CONFIRMING THE SELECTED PRE-AGREEMENT" in prompt
    assert "not to create a booking" in prompt
    assert "official commitment email" in prompt

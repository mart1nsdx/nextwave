"""The prompt is composed per call, not frozen at import.

This is the failure these tests exist for, and it is entirely silent: the composer and
every phase block can be present and correct while the live path quietly runs a single
prompt built once, against one company, one lane and one date. Nothing raises, nothing
logs, and the only symptom is the agent saying the wrong thing on a real call.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import app.agent as agent_package
from app.agent import (
    DEMO_PROFILE,
    CallPhase,
    build_greeting,
    build_system_prompt,
    demo_context,
    spoken_date,
    today_for,
)
from app.domain.models import CallDirection
from app.main import phase_for


def test_an_inbound_call_is_not_answered_with_an_outbound_pitch() -> None:
    """The bug in the flesh: someone calls us and hears us pitching a container."""
    inbound = build_greeting(DEMO_PROFILE, demo_context(CallPhase.INBOUND))
    rfq = build_greeting(DEMO_PROFILE, demo_context(CallPhase.RFQ))

    assert inbound != rfq
    # Whoever called has not said what they want yet, so we ask instead of announcing.
    assert "¿En qué le puedo ayudar?" in inbound
    assert "textiles" not in inbound and "tarifa" not in inbound
    assert "tarifa" in rfq


def test_each_phase_gets_its_own_rules() -> None:
    inbound = build_system_prompt(DEMO_PROFILE, demo_context(CallPhase.INBOUND))
    rfq = build_system_prompt(DEMO_PROFILE, demo_context(CallPhase.RFQ))

    # Identity verification is inbound-only, and it is the block that stops the agent
    # confirming a reference or a rate to a stranger who called in.
    assert "THIS CALL: SOMEONE CALLED US" in inbound
    assert "one operational fact" in inbound
    assert "THIS CALL: GETTING A QUOTE" in rfq
    assert "one operational fact" not in rfq


def test_phase_follows_direction_and_never_the_conversation() -> None:
    assert phase_for(CallDirection.INBOUND) is CallPhase.INBOUND
    assert phase_for(CallDirection.OUTBOUND) is CallPhase.RFQ


def test_today_is_read_now_in_the_company_timezone() -> None:
    """A frozen date breaks invariant #8 quietly: 'el jueves' resolves to the wrong day."""
    expected = datetime.now(ZoneInfo(DEMO_PROFILE.timezone)).date()

    assert today_for(DEMO_PROFILE) == spoken_date(expected, DEMO_PROFILE.primary_language)
    assert today_for(DEMO_PROFILE) in build_system_prompt(DEMO_PROFILE, demo_context(CallPhase.RFQ))


def test_no_prompt_is_composed_at_import_time() -> None:
    """The regression guard. A module-level prompt is one a caller gets by forgetting."""
    for frozen in ("SYSTEM_PROMPT", "GREETING", "RECOVERY_LINE", "DEMO_CONTEXT"):
        assert not hasattr(agent_package, frozen), (
            f"app.agent.{frozen} is composed at import and cannot know which call it is "
            "for; compose per call with build_system_prompt(profile, context) instead"
        )


def test_the_mandate_figures_are_rendered_but_marked_unspeakable() -> None:
    prompt = build_system_prompt(DEMO_PROFILE, demo_context(CallPhase.RFQ))

    assert "FIGURES YOU MUST NEVER SAY OUT LOUD" in prompt
    assert "9,000 MXN" in prompt

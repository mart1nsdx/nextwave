"""Pure authorization rules for transferring a live call to a person."""

from app.domain.models import HandoffReason


def handoff_is_authorized(reason: HandoffReason) -> bool:
    """Every enumerated safety reason escalates; unknown input cannot reach this function."""

    return reason in frozenset(HandoffReason)

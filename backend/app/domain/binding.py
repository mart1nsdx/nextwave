"""Which case a live call belongs to, and the mandate that governs it.

The seam that replaces "every call runs the demo operation". A `CallBinding` is produced
once per call, before the conversation starts, and is the *only* thing that tells the
rest of the system which operation is being negotiated and under whose authority.

It is deliberately small. The repository and schema layer this will eventually be read
from is being decided in two competing pull requests, so nothing here depends on either:
when one of them merges, the resolver in `app/main.py` starts reading rows instead of a
dict and this type stops changing. That is the whole point of keeping it this thin.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import CallDirection
from app.domain.security import Mandate

__all__ = ["CallBinding"]


class CallBinding(BaseModel):
    """One call, bound to one case. Frozen: nothing said on the call may edit it.

    Invariant #2 in structural form. The mandate travels with the call rather than being
    looked up again mid-conversation, so there is no moment at which a counterparty's
    words and a fresh read of the mandate could disagree.
    """

    model_config = ConfigDict(frozen=True)

    # Twilio's CallSid. Empty until the call is actually placed: an outbound binding is
    # written *before* the number is dialled, and the sid is patched in afterwards.
    call_sid: str = ""
    case_id: str = Field(min_length=1)
    operation_ref: str = Field(min_length=1)
    direction: CallDirection
    mandate: Mandate

    def with_call_sid(self, call_sid: str) -> "CallBinding":
        """The same binding, now that Twilio has told us which call it is."""
        return self.model_copy(update={"call_sid": call_sid})

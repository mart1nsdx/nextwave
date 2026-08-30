"""Outbound recap (email) and escalation handoff.

MAY IMPORT:  domain, config.
IMPORTED BY: tools, main.

Small but load-bearing: a commitment does not count until the written recap is out
(invariant #3), so a send failure here means RECAP_FAILED / NOT_COMMITTED. Separate from
telephony/ because it is a different vendor surface (SendGrid) with a different failure
mode.
"""

from app.notify.sender import NullRecapSender, SendGridRecapSender

__all__ = ["NullRecapSender", "SendGridRecapSender"]

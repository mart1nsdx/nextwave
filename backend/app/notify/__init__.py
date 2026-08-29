"""Outbound recap (SMS/email) and escalation handoff.

MAY IMPORT:  domain, config.
IMPORTED BY: tools.

Small but load-bearing: a commitment does not count until the written recap is out
(invariant #3), so a send failure here means RECAP_FAILED / NOT_COMMITTED. Separate
from telephony/ because it is a different vendor surface with a different failure mode.
"""

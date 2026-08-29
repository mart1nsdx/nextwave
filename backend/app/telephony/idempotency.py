"""Duplicate-delivery guard for Twilio webhooks.

Twilio retries. A retried status callback must not produce a second of anything
(AGENTS.md invariant #7).

This is deliberately the smallest thing that is correct for a single-process demo, and
it is honest about its limits: an in-process set does not survive a restart and is not
shared between workers. Real idempotency keys belong in ledger/, which every mutating
path already touches; this moves there when ledger/ lands.
"""

from collections import OrderedDict


class SeenEvents:
    """Bounded FIFO of keys already handled. `record` is the check and the write."""

    def __init__(self, capacity: int = 4096) -> None:
        self._capacity = capacity
        self._keys: OrderedDict[str, None] = OrderedDict()

    def record(self, key: str) -> bool:
        """True if this key is new (act on it); False if it is a redelivery (drop it)."""
        if key in self._keys:
            return False
        self._keys[key] = None
        if len(self._keys) > self._capacity:
            self._keys.popitem(last=False)
        return True

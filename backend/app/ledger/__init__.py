"""Append-only evidence: event log, audio offsets, idempotency keys.

MAY IMPORT:  domain, repo.
IMPORTED BY: market, tools.

Append-only is the point. A later utterance never edits an earlier one (invariant #4) —
it appends a new event with its own source and timestamp. A commitment with no audio
offset is EVIDENCE_MISSING, never `verified` (invariant #3).
"""

from app.ledger.evidence import EvidenceLedger

__all__ = ["EvidenceLedger"]

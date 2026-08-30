"""Persistence. OperationRepository — Supabase behind an interface.

MAY IMPORT:  domain, config.
IMPORTED BY: ledger, market, tools.

The interface exists so sim_call and the test suite can run against an in-memory
implementation with no network. All database access in the codebase goes through here;
a Supabase client constructed anywhere else is a bug.
"""

from app.repo.operations import InMemoryOperationStore, SupabaseOperationStore
from app.repo.store import InMemoryTranscriptStore, SupabaseTranscriptStore

__all__ = [
    "InMemoryOperationStore",
    "SupabaseOperationStore",
    "InMemoryTranscriptStore",
    "SupabaseTranscriptStore",
]

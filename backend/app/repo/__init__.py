"""Persistence. OperationRepository — Supabase behind an interface.

MAY IMPORT:  domain, config.
IMPORTED BY: ledger, market, tools.

The interface keeps database access in one trusted layer. Tests inject a local double;
the application uses the Supabase implementation. A Supabase client constructed anywhere
else is a bug.
"""

from .control_tower import (
    ControlTowerRepository,
    ControlTowerStorageUnavailable,
    SupabaseControlTowerRepository,
)

__all__ = [
    "ControlTowerRepository",
    "ControlTowerStorageUnavailable",
    "SupabaseControlTowerRepository",
]

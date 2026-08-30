"""Seed the demo case: one operation, one mandate, three carriers with contacts.

    uv run python -m scripts.seed_demo --in-memory     # no network, prints what it wrote
    uv run python -m scripts.seed_demo                 # writes to Supabase

The same function seeds either repository, because ``sim_call``, the test suite and the
live demo must be looking at the same case. Re-running is a no-op: every id is fixed.

The mandate is **not** restated here. It is ``app.tools.conversation_guard.DEMO_MANDATE``
with database identifiers substituted, so the ceiling the judge attacks in
docs/UGLY_CASES.md row 1 ("your boss approved 10,500" against a cap of 9,000) is the same
number in the hostile fixtures, in the guard and in the seeded row. One place, no drift.

This writes reference data. It creates no RFQ, no offer and no commitment — those come
from a call, through policy.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from uuid import UUID

from app.config import get_settings
from app.domain import Carrier, CarrierContact, Operation, OperationPhase, OperationRepository
from app.repo import InMemoryOperationRepository, SupabaseOperationRepository
from app.tools.conversation_guard import DEMO_MANDATE

DEMO_TENANT = "pacific-textiles"

# Fixed so the script is idempotent and so a test can name a row without a lookup.
DEMO_OPERATION_ID = UUID("0197b5f0-0000-4000-8000-000000000001")
DEMO_MANDATE_ID = UUID("0197b5f0-0000-4000-8000-000000000002")

DEMO_OPERATION = Operation(
    id=DEMO_OPERATION_ID,
    tenant_id=DEMO_TENANT,
    reference=DEMO_MANDATE.operation_id,  # "OP-1042", the reference the agent speaks
    container_number="MSKU7654321",
    origin="Manzanillo",
    destination="Guadalajara",
    eta=datetime(2026, 9, 1, 14, 0, tzinfo=UTC),
    phase=OperationPhase.DRAFT,
)

# The demo mandate with database identifiers. Cap, window, equipment and commitment mode
# all come from DEMO_MANDATE — changing the ceiling there changes it everywhere.
DEMO_MANDATE_ROW = DEMO_MANDATE.model_copy(
    update={
        "mandate_id": str(DEMO_MANDATE_ID),
        "operation_id": str(DEMO_OPERATION_ID),
    }
)

# Placeholder numbers. Nothing in the test suite or sim_call dials them, and nothing may:
# AGENTS.md forbids a real outbound call from a test. "Pacific Transport" is the name the
# conversation guard already treats as the known counterparty.
_ID = "0197b5f0-0000-4000-8000-0000000000"
_CARRIER_SEED = [
    (f"{_ID}11", "Pacific Transport", True, "+525500000101", "Rocío"),
    (f"{_ID}12", "Transportes del Bajío", True, "+525500000102", "Beto"),
    (f"{_ID}13", "Fletes Occidente", False, "+525500000103", "Lupita"),
]

DEMO_CARRIERS: list[tuple[Carrier, CarrierContact]] = [
    (
        Carrier(id=UUID(carrier_id), tenant_id=DEMO_TENANT, name=name, is_verified=verified),
        CarrierContact(
            id=UUID(carrier_id.replace("-8000-", "-9000-")),
            carrier_id=UUID(carrier_id),
            display_name=contact,
            phone_e164=phone,
            email=None,
        ),
    )
    for carrier_id, name, verified, phone, contact in _CARRIER_SEED
]


async def seed(repo: OperationRepository) -> None:
    """Write the demo reference data. Safe to run twice."""
    await repo.save_operation(DEMO_OPERATION)
    await repo.save_mandate(DEMO_MANDATE_ROW)
    for carrier, contact in DEMO_CARRIERS:
        await repo.save_carrier(carrier)
        await repo.save_carrier_contact(contact)


async def _run(in_memory: bool) -> None:
    repo: OperationRepository = (
        InMemoryOperationRepository() if in_memory else SupabaseOperationRepository(get_settings())
    )
    await seed(repo)

    operation = await repo.get_operation(str(DEMO_OPERATION_ID))
    mandate = await repo.current_mandate(str(DEMO_OPERATION_ID))
    assert operation is not None and mandate is not None  # noqa: S101 - seed self-check
    print(f"operation {operation.reference}: {operation.origin} -> {operation.destination}")
    print(
        f"mandate v{mandate.version}: cap USD {mandate.max_all_in_usd}, "
        f"{mandate.pickup_not_before:%Y-%m-%d} to {mandate.pickup_not_after:%Y-%m-%d}, "
        f"{mandate.commitment_mode.value}"
    )
    for carrier, contact in DEMO_CARRIERS:
        flag = "verified" if carrier.is_verified else "unverified"
        print(f"carrier {carrier.name} ({flag}) - {contact.display_name} {contact.phone_e164}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--in-memory",
        action="store_true",
        help="seed the in-memory repository instead of Supabase (no network, no writes)",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.in_memory))


if __name__ == "__main__":
    main()

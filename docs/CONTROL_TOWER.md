# Volta Control Tower

Volta is a decision console for the port-to-warehouse trucking leg. It makes the
demurrage clock actionable: an operator sees when an operation is ready, confirms RFQ
activation, compares auditable offers, and follows evidence through assignment.

## Product boundary

Volta owns drayage coordination after upstream signals say a container has arrived and
documents are ready. Arrival and document readiness remain read-only upstream signals;
Volta is not a pre-arrival document-management system.

The dashboard presents a compact Nauta relationship rail, not a fictional multi-agent
workspace. Every relationship is source-labelled. If a non-production record is ever
inserted in the database, its source must explicitly label it as such.

## Dashboard routes

| Route | Purpose |
| --- | --- |
| `/operations` | Work queue grouped by attention, active RFQ work, and execution. |
| `/operations/{id}` | Operation workspace: timeline, readiness, RFQ action, offers, assignment, and connected intelligence. |
| `/calls` | Call ledger and timestamped evidence. |
| `/operations/{id}/configuration` | Bot presentation preferences plus immutable authorization details. |

The dashboard has no direct Supabase client. It reads short-lived projections from the
API and polls only while an RFQ is open.

## API contract

Read projections:

- `GET /operations`
- `GET /operations/{id}/workspace`
- `GET /operations/{id}/calls`
- `GET /operations/{id}/configuration`
- `GET /calls`
- `GET /calls/{sid}/evidence`

Operator commands:

- `POST /operations/{id}/rfqs/{rfqId}/activate`
- `POST /operations/{id}/rfqs/{rfqId}/request-award`

Both commands require an `idempotency_key`. They are routed through `market` and the
deterministic policy layer; neither command writes a commitment. An award request only
locks the RFQ for the one award flow. It leaves the commitment unbooked until the existing
verification chain completes.

## Authorization configuration

`backend/app/domain/security.py` is the authoritative security kernel. `Mandate` is a
frozen Pydantic model and represents human authorization for exactly one operation.
Caller speech, model output, recap generation, and tool calls cannot modify it.

Changing policy means creating a new, authenticated mandate version. The API does not
invent an unauthenticated mandate-edit endpoint; authenticated ownership is required
before version creation can be exposed to operators.

For non-USD proposals, `evaluate_quote_proposal` requires an immutable `FxSnapshot` and
an approved `fx_margin_bps`. It rejects a future snapshot, one older than two hours, or a
non-USD proposal without a margin. Trusted carrier/session identity is also injected from
the carrier directory or authenticated session, never from caller claims.

## Persistence migration

`supabase/migrations/20260829205100_add_control_tower_schema.sql` creates the source
tables for operations, immutable mandate versions, FX snapshots, trusted sessions, call
evidence, commitments, and append-only assignment versions. It also creates the direct
`call_cases.operation_id` relation plus atomic RFQ/award RPCs that preserve idempotency
and never create a commitment.

`SupabaseControlTowerRepository` is the only production repository. It returns a
controlled `503` when the server has no Supabase configuration instead of falling back to
hard-coded operations. Populate the database through the upstream, market, voice, and
ledger workflows; this migration contains no seed data.

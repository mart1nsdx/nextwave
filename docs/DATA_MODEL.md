# Data model — why the schema is shaped this way

`ARCHITECTURE.md` explains the code structure. `DOMAIN.md` explains the world. `BUILD.md`
describes the data model as *shape*. This file explains the **decisions** taken turning that
shape into Postgres, so each can be challenged on its merits.

Schema lives in `supabase/migrations/`; every table and non-obvious constraint is commented
in the migration that creates it. Demo data is `supabase/seed.sql`.

---

## 1. Why Postgres

"Relational is the default" is not a reason. The reason is that **the project's thesis is
that the system refuses invalid states rather than trusting the agent to avoid them**, and
that thesis is only credible if it also holds one layer below the application — because the
application is where the agent lives.

Every `AGENTS.md` invariant that *can* be an integrity constraint is one:

| Invariant | Enforced by | Cost |
| --- | --- | --- |
| #5 One award per RFQ — "two open bookings is the worst failure" | `unique index on offers (rfq_id) where status = 'accepted'` | 1 line |
| #7 Handlers are idempotent | `unique (idempotency_key)` + `on conflict do nothing` | 1 line |
| #4 Never overwrite silently | `revoke update, delete` on the event tables, **including from `service_role`** | 1 line per table |
| #3 No commitment without evidence | trigger on `commitment_transitions` | ~15 lines |
| #2 One live mandate per operation | `unique index on mandates (operation_id) where status = 'active'` | 1 line |
| Container numbers are real | `iso6346_check_digit()` in a `check` | ~25 lines |

The award index is the argument in miniature. A system that dials three carriers at once has
a real race when two dispatchers confirm simultaneously. In Postgres the second write fails.
In application code it is a path someone has to remember to write, in the layer this
architecture explicitly distrusts.

**Why not Mongo.** `ARCHITECTURE.md` §9 rejects it on read-heaviness and JSONB, which is
right but incomplete. The sharper reason: every row above becomes application logic under a
document store. Partial unique indexes on a filtered subset, cross-table triggers,
table-level privilege revocation, and transactional multi-table writes are absent or
materially weaker — so adopting it would move the invariants into precisely the layer we
have declared untrusted. Volume never enters the argument: this is tens of calls and
megabytes, where no document-store performance claim engages.

**The trigger is not business logic.** It cannot authorize anything; it can only refuse, in
the same direction as a foreign key. `policy/` remains the sole grantor of permission. The
database is a second party that can say no.

## 2. Why this shape suits conversational data

Four properties of a phone call drive it:

1. **A conversation revises itself.** A dispatcher says 8,500, then 9,200. Both were said.
   So `offers` are append-only with `superseded_by`; a changed offer is a new row. A
   last-write-wins update would erase the fact the trial by fire is testing.
2. **The speaker changes mid-call** (`DOMAIN.md` §4.1). Commitments and offers reference
   `participant_segments`, never the call — otherwise an agreement is attributed to whoever
   happened to answer the phone.
3. **Evidence is a point in time, and there are two clocks.** See §4.
4. **The hot path does no queries, so the schema is not tuned for reads.** `BUILD.md` §7
   preloads before dialling and queues every write. The schema is optimised for one wide
   preload plus cheap appends — deliberately *not* for ad-hoc query performance. That is the
   honest optimisation claim, and it is why the database choice matters less than the
   latency discipline around it.

## 3. Money

Every monetary value is a **pair**: `bigint` minor units plus an explicit ISO 4217 code.
Never a bare number, never a float. Integer minor units make D-02A's "round upward to USD
cents, never down against a cap" an explicit decision in code rather than an artifact of
storage precision.

- `fx_rate_snapshots` is immutable **by privilege**. A policy decision cites the exact
  snapshot that priced it; if the row can change, the evidence is worthless.
- `usd_per_unit` names its own direction. An inverted rate is a silent 1000x authorization
  error, and a column name is cheaper than a test.
- `offers` carries a check: a *priced* non-USD offer must cite a snapshot, or its USD figure
  is an unfalsifiable claim.
- `offer_cost_components` decomposes the quote because the cap is an aggregate. One `total`
  column makes "plus tolls" invisible, makes `is_total_final` unknowable, and leaves the
  auditable comparison the demo requires with nothing to show.

**On conversion to MXN.** Conversion *logic* stays in Python — one implementation, `Decimal`,
in the `policy/` path. A plpgsql conversion function would be a second implementation of the
cap rule that can silently disagree with the first, which is the one failure this design
cannot absorb. The database stores the inputs and outputs as evidence and offers the
`offer_display` view, which renders a stored USD amount back into the quote currency using
the same snapshot the decision cited. **The view formats; it never decides.**

## 4. The clock problem

`voice/events.py` defines every STT offset as milliseconds since **Media Stream start**, and
`voice/stt/deepgram.py` rebases Deepgram's timeline onto the first frame. A Twilio recording
begins at a *different* instant. Storing only the offset means playback seeks the wrong
moment — which looks like working evidence and is not.

So `call_cases.clock_reference_at` holds the single reference of `BUILD.md` §2.1, and
`recordings.clock_offset_ms` holds the delta. Playback seeks
`evidence.audio_offset_ms − recordings.clock_offset_ms`.

**Nothing writes a recording yet**: no `<Record>` is configured anywhere in `telephony/`.
The table exists so wiring it is a write rather than a migration.

## 5. How data enters

| Source | Path | Idempotency |
| --- | --- | --- |
| Twilio webhooks (status, recording, DTMF) | `telephony/` → `ledger_events` | `idempotency_key`, `on conflict do nothing` |
| Twilio Media Streams → Deepgram | `telephony/` → `voice/` → `call_transcript_events` | `(case_id, track, sequence_number)` |
| LLM tool calls | `voice/` → `tools/` → `policy_decisions`, `tool_invocations` | per invocation id |
| Resend delivery webhooks | `notify/` → `call_recap_deliveries` → advances the chain | provider message id |
| FX provider | server-side fetch → `fx_rate_snapshots`. **Never from model output or caller speech** | `(provider, currency, observed_at)` |
| Dashboard mandate writes | Supabase Auth OTP + fresh TOTP → backend → new mandate version | fresh TOTP per write |
| **The Supabase MCP** | **Development only** — schema management by us. Not a runtime path; the agent never reaches Supabase through MCP | n/a |

Writes during a call are queued, never awaited. The database is not on the conversational
hot path.

## 6. RLS

Tables are RLS-enabled with **no policies** by default, which is deny-all for `anon` and
`authenticated` while `service_role` (the backend) bypasses. The security advisor reports
this as INFO on those tables; it is the intended posture, not an oversight.

The read-model tables additionally carry a `select`-only policy for `authenticated`.
`BUILD.md` §2.1 promises Persona 4 a read model over **Supabase Realtime**, and
`postgres_changes` fires against tables under RLS — a backend proxy cannot deliver it. This
reverses the comment in `20260829125514`; it needs that migration's author to ack.
`using (true)` is correct for one tenant and becomes a tenant predicate the day there is a
second, which is why `tenant_id` is already on every row.

## 7. What we deliberately did not do

| Rejected | Why |
| --- | --- |
| A SQL function for FX conversion | A second implementation of the cap rule that can disagree with `policy/`. See §3. |
| `pgvector` | Cut list. `analysis/` only, over historical briefs, after the call. |
| `pgmq` | An in-database queue defeats the point of keeping the database off the hot path. |
| An ORM | The Supabase client in `repo/` is the one access path; a second is a bug. |
| Partitioning | Tens of calls. |
| Storing a single `total` on an offer | Makes "plus tolls" invisible and the cap bypassable by naming. |
| `updated_at` on the event tables | They are append-only. There is nothing to update. |
| Enforcing the commitment chain order in SQL | The database refuses states, but the *transition rules* are `policy/`'s and must stay testable in Python without a database. |

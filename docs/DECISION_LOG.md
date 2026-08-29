# Decision log

One entry per decision that a teammate could reasonably have made differently. The point
is not ceremony — it is so that in hour 18 nobody re-litigates a tradeoff from hour 2, and
so the "why" survives into the demo. Newest at the bottom.

Format: what was decided, what it beat, and what would make us change our mind.

---

## D1 — Deterministic policy engine, not an LLM safety check

**Decided:** authorization is plain Python in `backend/app/policy/`. The price cap is an
`if` statement.

**Beat:** asking the model to self-check ("do not exceed the cap"), which is the default
approach and reads well in a prompt.

**Why:** a prompt-based check fails exactly when it matters — when a persuasive human
argues with it. The trial-by-fire is an adversarial human on the phone. A deterministic
gate cannot be argued with.

**Would change if:** never, for authorization. This is the project's thesis.

## D2 — `domain/` as a shared leaf package

**Decided:** core types (Operation, Quote, Commitment, Mandate) live in `domain/`, which
imports nothing.

**Beat:** putting them in `policy/`, which would have kept the package count lower.

**Why:** `tools/`, `ledger/`, `repo/`, and `market/` all need `Quote` and `Commitment`.
Without a leaf they either duplicate or all import from `policy/`, which destroys the
"policy is a pure sink" property that the whole design rests on. One directory buys a
clean acyclic graph.

**Would change if:** the type set stays under ~3 classes, which it won't.

## D3 — Layering enforced by a test, not a convention

**Decided:** `backend/tests/test_layering.py` holds the allowed-import map as data and
fails the build on any edge outside it.

**Beat:** documenting the layering in `AGENTS.md` and trusting reviewers.

**Why:** four people and their agents editing in parallel for 24 hours. A convention that
is only in a doc degrades within hours, and the degradation is invisible until a judge
exploits it live. ~40 lines of stdlib `ast` makes it structural. We verified it fails
before trusting it.

**Would change if:** it produces false positives that slow people down. It hasn't.

## D4 — uv over pip + requirements.txt

**Decided:** `uv` with a committed `uv.lock`, Python pinned to 3.12.

**Beat:** the `venv` + `requirements.txt` flow originally written into `AGENTS.md`.

**Why:** four people syncing dependencies repeatedly on a shared clock. Fast resolution
and a real lockfile mean "works on my machine" doesn't cost anyone 20 minutes. 3.12
rather than 3.14 for wheel availability across twilio/supabase/pydantic.

**Cost:** everyone needs `uv` installed. Accepted.

## D5 — Vite + React for the dashboard, not Next.js

**Decided:** Vite + React + TypeScript, one screen, no router, no state library.

**Beat:** Next.js, which the original `.gitignore` implied.

**Why:** the dashboard is one read-mostly screen. Next.js brings SSR, routing, and an API
layer we would not use — capability we couldn't justify if asked why it's there. The
backend already owns the API.

**Would change if:** the dashboard needed server-side auth or multiple routes.

## D6 — Communal CHANGELOG.md, cross-cutting changes only

**Decided:** one root `CHANGELOG.md`, newest-first, written only when a change affects
someone else's module or a shared contract.

**Beat:** (a) a `changelog.d/` fragment directory generated into a file, which is
structurally merge-conflict-free; (b) logging every commit.

**Why:** the log's job is "what did the other three change while I was heads down?" —
which needs one chronological view you read top-down, and needs to stay short enough to
actually read. Fragments solve conflicts but add a build step and aren't readable until
generated. Logging every commit duplicates `git log` with worse tooling.

**Cost:** concurrent appends conflict. Mitigated by a rule in both `AGENTS.md` and the
file header: keep both entries, order by timestamp, never resolve by deleting.

---

## D7 — Verification, notification, and recap pipeline

**Decision:** Transcribe the live Twilio call (Deepgram streaming STT), save append-only,
idempotent transcript events to Supabase linked to `CallSid` and audio offsets, then run
recap generation *after* the call and email it before any commitment is verified.

**Options considered:** Transcribe only after the call, let the voice model create
commitments in real time, or persist one mutable transcript without audio offsets.

**What we choose:** Post-call `RecapService` reads the persisted transcript, generates the
recap + brief (OpenAI), emails the recap (SendGrid), and stores the delivery status. A
failed send (`RecapDelivery(status=failed)`) means the commitment stays uncommitted.

**Why:** preserves an auditable click-to-audio record and prevents an unverified model
utterance, dashboard action, or notification failure from creating a booking.

**Full design, file map, env vars, and runbook:** `docs/VERIFICATION.md`.

## D-DB-01 — Postgres constraints carry the invariants, not application code

**Decided:** every `AGENTS.md` invariant that can be expressed as an index, check, privilege
or trigger is expressed that way. See `docs/DATA_MODEL.md` §1 for the mapping.

**Beat:** enforcing all of them in `policy/` and treating the database as storage.

**Why:** the project's thesis is that the system refuses invalid states rather than trusting
the agent to avoid them. That is only credible if it also holds below the application, since
the application is where the agent lives. "Two carriers confirm at the same instant" is a
real race when we dial three at once; a partial unique index makes the second write fail
instead of relying on a code path someone remembered.

**Would change if:** a constraint starts rejecting legitimate paths. One already did — see
D-DB-03.

## D-DB-02 — Conversion logic in Python, conversion evidence in the database

**Decided:** FX conversion happens once, in `policy/`, with `Decimal`. The database stores
the snapshot, the inputs and the result, and exposes the `offer_display` view to render a
stored USD amount back into the quote currency.

**Beat:** a plpgsql conversion function, which is what "add conversion functions to MXN"
most directly suggests.

**Why:** a SQL function would be a second implementation of the cap rule, able to disagree
silently with the first. Two sources of truth for "is this within the mandate" is the one
failure this architecture cannot absorb. The view formats; it never decides.

**Would change if:** never for authorization. A display-only helper is fine.

## D-DB-03 — Mandate lifecycle keyed on `status`, not on `superseded_by`

**Decided:** `mandates.status` defines which version is active; `superseded_by` is only the
link to the replacement.

**Beat:** the original design where `superseded_by is null` meant "active".

**Why:** that design made supersession impossible in either order — inserting the new version
violated the one-active index, and updating the old row first violated the foreign key to a
version that did not exist yet. A deferrable constraint would fix it, but Postgres cannot
defer a *partial* unique index. Found by trying to raise a cap on the seed data, which is
the argument for exercising a schema rather than reviewing it.

**Note:** the constraint was right and the schema was wrong. It correctly refused two live
mandates; it also refused the legitimate path, and that is a schema bug.

## D-DB-04 — ISO 6346 check digits enforced in the database

**Decided:** a `check` constraint validates the container-number check digit, not just its
shape.

**Beat:** the JSON-schema pattern alone (four letters, seven digits).

**Why:** while writing the constraint tests for this branch, two invented container numbers
passed the pattern and were wrong. `DOMAIN.md` warns that a logistics judge will notice. It
is a format check in the same class as the E.164 regex on phone numbers — deterministic, no
authority, refuses but never grants.

**Cost:** ~25 lines of plpgsql. Verified against an independent Python implementation.

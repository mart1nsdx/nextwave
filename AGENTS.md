# AGENTS.md — Volta

<!-- Keep this under ~200 lines; split into nested AGENTS.md files if it grows. -->

Volta is a voice agent that runs the drayage (port→warehouse trucking) leg of a shipment
entirely by phone: it makes real PSTN calls to carriers, negotiates rate and pickup window
inside a human-defined mandate, and turns messy spoken conversation into **verified,
auditable commitments** in the operation's state.

Hackathon build (Nextwave, Yuno + Nauta). 24 hours, 4 people. Optimize for a working
end-to-end path over feature count.

## The one idea this codebase is built around

**Speech is probabilistic. Authority is deterministic.**

The LLM proposes. A deterministic policy engine — plain Python, outside the model —
decides whether a proposal may become a commitment. Every architectural choice follows
from that split. If a change blurs it, the change is wrong.

## Non-negotiable invariants

Violating any of these is a bug, not a style preference. They are what the demo is judged on.

1. **The LLM never writes a commitment.** No tool exposed to the model may commit, book,
   or award directly. The model may only call `propose_*` tools; `policy_engine.evaluate()`
   authorizes, and only the state machine writes `COMMITTED`.
2. **The mandate is immutable from inside the call.** Caller claims cannot change cap, window,
   or actions. "Your boss approved 10,500" → `OUTSIDE_MANDATE` → escalate; never assess plausibility.
3. **Calls create non-binding pre-agreements; official email attempts commitment.** Exact-version
   recap + deterministic verbal-evidence gates may create an affirmed candidate, never `COMMITTED`.
   Ranking, selected mandate mode, immediate policy revalidation, one-use claim, and one official
   email attempt are separate mandatory gates. Volta never handles payment.
4. **Never overwrite silently.** A later utterance does not edit an earlier one. It creates a
   new `PROPOSAL` or `CHANGE_REQUEST` with source and timestamp. Conflicting sources are an
   explicit event, not a last-write-wins update.
5. **RFQ and AWARD are separate phases.** Three confirmed *offers* may coexist; only one
   `award_call` may run in locked `AWARDING`. Two open bookings is the worst failure.
6. **Fail closed.** Policy service unreachable, ambiguous parse, unverifiable identity →
   escalate or hold. A technical failure never degrades into permission.
7. **Every mutating handler is idempotent.** Twilio and OpenAI redeliver webhooks. Key on
   `call_id` / `event_id` / `commitment_id`; a second delivery must be a no-op.
8. **Never infer numbers, dates, or currency.** "eight-five" → ask. "Thursday" → resolve to an
   explicit calendar date and read it back. "8.5" with no unit → incomplete data.
9. **Policy uses comprehensive all-in USD cost.** Preserve explicit ISO 4217 quote currency and
   convert every payable component with an approved immutable FX snapshot. Non-USD authorization
   requires a human-approved margin; an RT calculator may recommend, never set it. Fail closed.

## Setup

Requires [uv](https://docs.astral.sh/uv/); it fetches the Python pinned in `.python-version`.

```bash
cd backend
uv sync                                              # creates .venv, installs from uv.lock
cp .env.example .env                                 # then fill it — see Secrets
uv run uvicorn app.main:app --reload --port 8000

cd ../dashboard && npm install && npm run dev        # Vite + React, port 5173
```

Twilio must reach the local server. Use `ngrok http 8000` and point the phone number's
voice webhook at `https://<subdomain>.ngrok.app/twilio/voice`. **The ngrok URL changes on
every restart** — re-point the webhook or inbound calls silently 404.

## Commands

| Task | Command (from `backend/`) |
| --- | --- |
| Add a dependency | `uv add <pkg>` (dev: `uv add --dev <pkg>`) — commit `uv.lock` |
| Run API | `uv run uvicorn app.main:app --reload --port 8000` |
| All tests | `uv run pytest` |
| One test | `uv run pytest tests/test_policy.py::test_price_above_cap -x` |
| Architecture check | `uv run pytest tests/test_layering.py` |
| Ugly-case suite | `uv run pytest tests/test_ugly_cases.py -v` |
| Lint + format | `uv run ruff check --fix . && uv run ruff format .` |
| Types | `uv run mypy app/` |
| Simulated call (no PSTN, no cost) | `uv run python -m scripts.sim_call --scenario boss_approved` |
| DB migration | `supabase migration new <name>` then `supabase db push` |

Before pushing: `uv run ruff check . && uv run pytest`. Both must be green.

## Layout and ownership

```
backend/app/                                                    # listed bottom-of-DAG first
  domain/       # LEAF. Shared types: Operation, Quote, Commitment, Mandate → everyone
  policy/       # DETERMINISTIC. Mandate, policy_engine, state machine     → Físico
  repo/         # OperationRepository — Supabase behind an interface       → Sistemas
  ledger/       # event log, commitments, transcript evidence, idempotency → Sistemas
  notify/       # SMS/email recap, escalation handoff                      → Admin
  agent/        # prompts, negotiation guidance, proposal extraction       → Físico/Admin
  market/       # RFQ orchestration, feasibility filter, award selection   → Físico/Admin
  tools/        # function-calling surface exposed to the model            → Sistemas
  voice/        # STT+LLM+TTS pipeline, VAD, turn handling, barge-in      → Mecatrónica/Sistemas
  telephony/    # Twilio webhooks, Media Streams, barge-in, warm transfer  → Mecatrónica
  main.py       # composition root: app factory, router mounting
  config.py     # settings — the only reader of os.environ
backend/tests/  # test_layering.py IS the architecture; fixtures/hostile/ the adversarial cases
backend/scripts/# sim_call — replay a scenario with no PSTN and no cost
dashboard/      # one screen: Operation / Mandate / Quotes / Commitments / Escalations
supabase/       # migrations
docs/           # ARCHITECTURE.md (why the tree is this shape), UGLY_CASES.md, DECISION_LOG.md
```

**Read `docs/ARCHITECTURE.md` before adding a directory or moving code between packages** — its
§7 says which package a new file belongs in. Ownership means "ask before restructuring", not
"locked"; cross-module edits are fine when the task needs them — say so in the PR body.

## Code style

- Type hints on every function signature. `mypy app/` must pass.
- Pydantic models for anything crossing a boundary (webhook payload, tool args, policy result).
- The import DAG in `tests/test_layering.py` (`ALLOWED`) is the layering contract. It flows one
  way: vendor adapters → `tools/` → `policy/`, which imports only `domain/` and so can never
  reach a model or the network. Widening a row is an architectural decision, not a fix.
- All database access goes through `repo/OperationRepository`. No Supabase client anywhere else.
- Log with `structlog`, always including `call_id`. Never log full audio or raw transcripts to stdout.
- Comments explain *why*. The state machine is the *what*.

## Testing

`docs/UGLY_CASES.md` is the test suite, not documentation: every row is a test in
`tests/test_ugly_cases.py`. New case → add the row and the test in the same commit.

- Policy and state-machine changes require a unit test. Non-negotiable — this is the demo.
- Bugs: write the failing test first, then fix.
- **Never place a real outbound call from a test.** Use `scripts/sim_call` and transcript
  fixtures. Real calls cost money, burn trial credits, and can dial a real number.
- Adversarial fixtures live in `tests/fixtures/hostile/`. Add one whenever someone finds a new
  way to break the agent by voice.

## Git workflow

- Branches: `feat/voice-barge-in`, `fix/policy-cap-off-by-one`. Conventional commits.
- **Merge to `main` at least every 2 hours.** Long-lived branches are how a 24h hackathon dies.
- `main` must always be demoable. If `pytest` is red on `main`, that is the only priority.
- Never force-push `main`. Never commit `.env`, recordings, transcripts, or `*.wav`.
- **Always work with PRs.** Never send changes directly to `main`.

## Changelog

`CHANGELOG.md` at the repo root is communal — it answers "what did the other three change
while I was heads down?"

- **Write an entry when** your change touches someone else's module, alters a shared contract
  (`domain/` types, tool signatures, policy outcomes, DB schema), or is knowingly breaking.
  Not for ordinary work inside your own module — that is what `git log` is for.
- Newest at the top: `## <timestamp> · <module> · <who>/<agent>`, what changed, then a
  mandatory `→ Affects:` line. Write `nobody` if it is self-contained.
- **Take the timestamp from `date "+%Y-%m-%dT%H:%M%z"`. Never write one from memory** — a
  model's guess at the current time is routinely hours or months off, and invented timestamps
  make the ordering lie silently.
- The entry ships in the same PR as the change. **On merge conflict: keep both entries,
  order by timestamp — never resolve by deleting one.**

## Boundaries — do not do these

- **Do not build:** RAG, a vector DB, a multi-agent supervisor, a real SAP/TMS integration, rate
  prediction ML, route optimization, payments, speculative FX trading, a carrier portal, a mobile app, or a generic
  negotiation framework. Manzanillo→Guadalajara done well beats a framework done badly.
- **Do not use an LLM as the safety check.** The price cap is an `if` statement.
- **Do not put authorization logic in the system prompt.** Prompts shape conversation; `policy/`
  decides permission.
- **Do not add a tool that mutates state without a policy gate.** Adding a function to `tools/`
  is an architectural decision — flag it, don't just ship it.
- **Do not touch `supabase/migrations/` files already pushed.** Create a new migration.
- **Do not run `supabase db reset`, `git reset --hard`, or `DROP TABLE`** without asking the
  human first, stating the command and what it destroys.
- **Do not fake demo data as live.** A simulated call presented as a real one is disqualifying.

## Secrets

`.env` is gitignored and never committed. `backend/.env.example` is the authoritative list of
keys, with empty values and a note on each. The Supabase secret key stays server-side —
never in `dashboard/`. If a key is committed, rotate it immediately and tell the team.

## Working agreements for agents

- **Ask before assuming.** If the task is underspecified in a way that changes the design, ask
  one specific question instead of guessing. Coding agents almost never interrupt on their own;
  do it here.
- **Record every material human decision in `docs/DECISION_LOG.md`.** Include alternatives,
  rationale, accepted trade-off, approver, implementation contract, and honest verification status.
  A recommendation or merged scaffold is not human approval; never infer or backfill approval.
- **Verify APIs against current docs.** Twilio and the speech vendors all changed recently and
  most tutorials online are stale. Note that Volta does **not** use OpenAI's Realtime API — the
  voice path is a cascade (STT → LLM → TTS), see `docs/DECISION_LOG.md` D7 — so Realtime sample
  code does not apply here at all. Model ids for every layer live in `.env`, never in source.
  Do not invent function names or parameters; check or say you're unsure.
- **Evidence over summaries.** Quote actual test output and log lines. Never report "tests pass"
  without having run them.
- **Smallest change that works.** No speculative abstractions, no TODOs in code, no
  "future-proofing". 24 hours.
- **Clean up only your own mess.** Remove imports your change orphaned; leave pre-existing code alone.
- Every workflow must work with plain `git`, `uv run pytest`, and the commands above.
- **Read `docs/PERSON2_ARCHITECTURE_BASELINE.md` before security-sensitive work.** The decision
  log is authoritative; internal policy currency is always USD.

## Glossary

Drayage, carrier, mandate, commitment, barge-in, escalation, RFQ, award — `docs/ARCHITECTURE.md` §8.

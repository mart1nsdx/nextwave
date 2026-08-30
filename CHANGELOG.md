# Changelog

**What this is for:** answering *"what did the other three change while I was heads
down?"* — not release notes. Newest at the top; read down until you hit something you've
already seen.

**Write an entry when** your change touches someone else's module, alters a shared
contract (`domain/` types, tool signatures, policy outcomes, DB schema), or is knowingly
breaking. Not for ordinary work inside your own module — that is what `git log` is for.

**Format** — three parts, and the `→ Affects:` line is the whole point:

```
## <timestamp> · <module> · <who>/<agent>
What changed, in one or two lines.
→ Affects: who has to do something about it. Literally "nobody" if self-contained.
```

**Get the timestamp from `date "+%Y-%m-%dT%H:%M%z"`. Never write one from memory** — a
model's guess at the current time is routinely hours or months off, and a log with
invented timestamps is worse than no log, because the ordering lies silently.

> **Merge conflicts here:** keep **both** entries and order them by timestamp.
> **Never resolve a conflict in this file by deleting an existing entry.**

---

## 2026-08-29T19:12-05 · scripts · Martin/claude
`award_from_recaps.py --commit --sms` now texts the negotiation specs (carrier, container,
tarifa, ventana, condiciones) to the awarded carrier's `counterparty_contacts.phone` via
Twilio — and to no one else. `--sms` requires `--commit`; a Twilio/credential failure is
reported, never fatal. The SMS body + result land in the JSON artifact.
→ Affects: nobody. Uses the existing TWILIO_* creds in backend/.env.

## 2026-08-29T19:03-05 · scripts · Martin/claude
`award_from_recaps.py` now scopes strictly to one container / RFQ: it only compares
carrier calls tied to that RFQ and excludes any other recap as noise. A call is tied by
`call_cases.metadata->>'rfq_id'`, by an `offers` row, or by `--assign` (which `--commit`
persists into `call_cases.metadata` as `{rfq_id, operation_ref, counterparty_id,
container_number}`). If nothing is tied, it refuses rather than guessing.
→ Affects: whoever wires the live outbound-call path — stamp those same
  `call_cases.metadata` keys when the agent dials a carrier for an operation, so the
  post-call comparison needs no manual `--assign`.

## 2026-08-29T18:55-05 · tests · Martin/claude
`test_voice_webhook_hands_the_call_to_our_socket` now forces `InMemoryTranscriptStore`.
With a real `backend/.env` present it was building a live Supabase client and its
`/twilio/voice` POST wrote a `call_cases` row to the shared project on every `pytest` run.
→ Affects: nobody. If you saw stray `CA0123456789abcdef` rows in Supabase, this was why.

## 2026-08-29T18:51-05 · scripts · Martin/claude
New `backend/scripts/award_from_recaps.py`: post-processing tool that reads the
`call_recaps` of one RFQ, normalises each carrier's quote (LLM extraction, never
inference), scores them with an explainable formula, drafts the confirmation email, and
— only with `--commit` — writes `offers` + `participant_segments` + a `commitments` row
at `chain_state='VERBAL'` (+ `commitment_transitions`). It is NOT the live call path and
never reaches `COMMITTED` (the DB evidence trigger and the real chain still gate that).
Dry-run by default; refuses to award a carrier whose recap has no confirmed price.
→ Affects: nobody yet — standalone, opt-in. It writes to the advanced drayage schema
  (`offers`, `commitments`, …) that the deployed Supabase project already has; those
  tables are not in `backend/app/` or the migrations on this branch yet.

## 2026-08-29T18:29-05:00 · domain, policy, tools, repo, supabase · Codex
Added the audited handoff contract: deterministic authorization, one idempotent request
per call, append-only lifecycle records, and the corresponding Supabase migration.
→ Affects: telephony and dashboard. Apply the new migration before using persisted handoffs.

## 2026-08-29T18:09-05 · voice, config · Codex
Raised the local barge-in gate from 900 RMS for 120 ms to 1800 RMS for 300 ms and added
a regression test for sustained moderate background noise.
→ Affects: anyone testing calls. Restart the backend after pulling; tune the two
  `VAD_BARGE_IN_*` variables only if the actual phone line still needs calibration.

## 2026-08-29T17:27-05 · config, repo, supabase · Codex
Replaced the legacy `SUPABASE_SERVICE_ROLE_KEY` configuration with
`SUPABASE_SECRET_KEY` for backend-only evidence persistence.
→ Affects: everyone running the backend. Replace the old `.env` variable with the
  Supabase `sb_secret_...` key; never expose it to the dashboard.

## 2026-08-29T17:23-05 · supabase, domain, agent · Codex
Added `call_recaps.agreement_candidates` as a non-null JSONB array for audio-anchored
agreement evidence. The model writes candidates only; deterministic policy remains the
sole future authority that can write commitments.
→ Affects: dashboard and policy. Read the candidates from the persisted recap; never
  treat them as `COMMITTED` without the policy and written-recap gates.

## 2026-08-29T17:12-0500 · supabase · Diego/claude
Policy and evidence spine: 22 new tables (operations, mandates, rfqs, offers + cost
components, commitments + transitions, evidence, policy_decisions, ledger_events,
participant_segments, fx_rate_snapshots, drayage vertical). All six migrations are now
applied to the `Execute` project, which was empty -- including the two on `martin`.
→ Affects: **everyone.** `SUPABASE_URL` must point at `hizwyjrjvzrdohuxklle`; the schema
  existed nowhere before this. `call_recaps`/`call_briefs`/`call_recap_deliveries` gained
  `case_id` (the `call_sid` FK still works). `call_cases` gained `provider`,
  `provider_call_id`, `clock_reference_at`. `call_transcript_events` gained `confidence`.
  Persona 4: read-model tables now carry a `select` policy for `authenticated`, so Realtime
  works -- this reverses the RLS comment in `20260829125514` and needs martin's ack.
  Persona 1: `recordings` exists and is empty because no `<Record>` is configured anywhere.
  Reasoning in `docs/DATA_MODEL.md`.
## 2026-08-29T16:47-05 · voice, telephony, ledger, repo, agent · Codex
The live bidirectional call now opens an evidence case, persists final caller and agent
turns with Twilio audio offsets, and produces persisted recap and call-brief reports when
Twilio closes the call. Report output contains audio-anchored agreement candidates only;
it does not write commitments or send any message.
→ Affects: dashboard and policy. Read `/calls/{call_sid}/transcript`, `/recap`, and
  `/brief`; a later deterministic policy step must validate candidates before commitment.

## 2026-08-29T17:36-0500 · agent, domain · Nacho/claude
The system prompt is no longer one hardcoded string. `domain.CompanyProfile` (new — the
dashboard's pre-registration) and `agent.CallContext` compose it per call:
`build_system_prompt(profile, context)`, `build_greeting(...)`, `recovery_line(...)`,
`escalation_line(...)`. Four phases — RFQ, AWARD, RENEGOTIATION, INBOUND — each get their
own block over a shared core. `build_agent(..., instructions=...)` is keyword-only and
defaults to the demo lane, so nothing downstream changed yet. The mandate ceiling and
target are now rendered into the prompt, marked never-say: a deliberate trade, see
DECISION_LOG D8; `policy/` is still the only thing that authorizes anything.
→ Affects: whoever wires `voice/session.py` to a real operation — pass the composed
prompt and greeting instead of the module-level `SYSTEM_PROMPT` / `GREETING`. Físico:
`domain/Operation` and `domain/Mandate` should map *into* `CallContext`, not replace it.

## 2026-08-29T14:25-0500 · agent, voice · Nacho/claude
`build_agent(model, api_key, tools=None)` — the key is now a required argument. It has to
be: pydantic-settings loads `.env` into a `Settings` object and never exports to
`os.environ`, so any library that reads the environment itself sees nothing, and the SDK
did. That failed only once a real call reached the model. Also `AudioSource` gained a
`call_id` property, and SDK tracing is off — it uploads what was said on the call.
→ Affects: whoever picks up `agent/` and `tools/`. Call `build_agent` with the key.
  Model settings are tuned for the phone (minimal reasoning, low verbosity, 12s timeout):
  at its defaults `gpt-5-mini` took nine seconds to answer, which on a call is a hang-up.
  If you change `OPENAI_AGENT_MODEL` to a non-reasoning model, drop the `reasoning=` field.

## 2026-08-29T14:10-0500 · domain, repo, ledger, agent, notify, supabase · Martin/claude
Added the call-evidence, post-call recap and recap-delivery building blocks, including
the Supabase migration. The incompatible Twilio transport is adapted separately to the
existing bidirectional voice path.
→ Affects: everyone. Evidence and recap types are shared contracts; run the new Supabase
  migration before enabling persisted call review.

## 2026-08-29T14:02-0500 · scripts · Nacho/claude
`uv run python -m scripts.point_number` repoints the Twilio number at whatever tunnel is
running and writes `PUBLIC_BASE_URL` into `.env`, so the server and the webhook cannot
disagree. Run it every time the tunnel restarts — a stale webhook raises nothing, calls
just 404 and the caller hears silence.
→ Affects: everyone who tests by phone. **Windows Defender blocks ngrok as unwanted
  software** — it silently deletes the binary mid-install, which looks like a broken scoop
  shim. Use cloudflared instead: `scoop install cloudflared`, then
  `cloudflared tunnel --url http://localhost:8000 --metrics localhost:20241`. No account,
  no authtoken. The script finds either tunnel, or takes `--url`.

## 2026-08-29T13:45-0500 · voice, agent, telephony · Nacho/claude
The voice pipeline is live end to end: Deepgram STT → OpenAI (Agents SDK) → Deepgram TTS,
with turn-taking and barge-in. `/twilio/media` now runs the agent; the echo diagnostic moved
to `/twilio/voice/echo`. New in `agent/`: `build_agent(model, tools=[])` and the system
prompt — it deliberately contains **no** price cap, window or permission (that is `policy/`).
`tools=` is already a parameter, so wiring `propose_*` tools needs no change to the audio path.
Adds `openai-agents` and `python-multipart`.
→ Affects: whoever owns `agent/` and `tools/`. The prompt in `agent/prompts.py` is yours to
  rewrite — keep authorization out of it. `tools/` plugs into `build_agent(tools=[...])`.
  `uv sync` after pulling. `uv run python -m scripts.sim_call --scenario boss_approved`
  replays a hostile call with no PSTN leg and no cost — add scenarios there, not by dialling.

## 2026-08-29T13:15-0500 · voice, telephony, config · Nacho/claude
`realtime/` is now `voice/`. We are not using OpenAI's Realtime API — the voice path is a
cascade (Deepgram STT → OpenAI via the Agents SDK → Deepgram TTS) that we orchestrate, so
that barge-in is our code and STT/TTS vendors are swappable. Reasoning in
`docs/DECISION_LOG.md` D7. `ALLOWED` in `tests/test_layering.py` renames the `realtime`
row to `voice` and repoints `telephony`. `config.py` drops `OPENAI_REALTIME_MODEL` (now
orphaned) and adds `OPENAI_AGENT_MODEL`, the Deepgram keys, provider/model selection, and
six `VAD_*` tunables.
→ Affects: everyone. `git pull` will leave you with a stale empty `app/realtime/` —
  delete it. Re-copy `backend/.env.example` to `.env`: the speech and VAD keys are new and
  `OPENAI_REALTIME_MODEL` is gone. If you were about to import `app.realtime`, it is
  `app.voice`. Audio is mu-law 8 kHz end to end — do not add a resampling step without
  reading `voice/frames.py` first.

## 2026-08-29T12:19-0500 · repo-wide · Diego/claude
Initial project structure: `backend/` (FastAPI, uv, 10 packages + `domain/` leaf),
`dashboard/` (Vite + React), `supabase/`, and `docs/ARCHITECTURE.md` justifying every
directory. Layering is enforced by `backend/tests/test_layering.py`, not by convention.
→ Affects: everyone. Read `docs/ARCHITECTURE.md` §7 before adding code — it says which
  package your file belongs in. Setup is now `uv sync`, not `pip install -r`; commands
  in `AGENTS.md` are `uv run …`. Adding a directory under `app/` fails the build until
  you declare its imports in `ALLOWED`.

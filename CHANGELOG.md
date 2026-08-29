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

## 2026-08-29T16:37-0500 · notify/policy/security · Person 2/Codex
Human-approved D34/D-04I: Resend serves two strictly separate email capabilities—a visibly
non-binding pre-agreement recap and a deterministic authorized official commitment.
→ Affects: everyone. Share transport only; separate commands/templates/capabilities/states,
  bind webhook type, reserve combined quota for commitments, and never equate recap with authority.

## 2026-08-29T16:21-0500 · notify/policy/security · Person 2/Codex
Human-approved D33/D-04H: Resend Free is the hackathon official commitment-email provider,
within 100/day and 3,000/month at USD 0/month, using one verified custom domain.
→ Affects: Person 2/3/4. Keep keys server-side, derive recipients from verified records,
  use canonical templates, verify webhooks, meter quota, and never overstate delivery evidence.

## 2026-08-29T16:18-0500 · domain/policy/dashboard/security · Person 2/Codex
Human-approved D32/D-04G: select the lowest comprehensive buffered all-in USD candidate
after all hard constraints, using deterministic delivery/time/ID tie-breaks.
→ Affects: everyone. No price-eligible candidate means no email and human escalation;
  only the authenticated owner may raise the bound, keep it, renegotiate, or abandon.

## 2026-08-29T16:15-0500 · domain/policy/realtime/notify/security · Person 2/Codex
Human-approved corrective D31/D-04F: calls create non-binding carrier-confirmed
pre-agreements; the official canonical email is the commitment attempt. D29/D30 superseded.
→ Affects: everyone. Mandate selects `AUTONOMOUS` or `HUMAN_ESCALATION`; policy compares
  and revalidates before one email dispatch. Volta has no payment capability or payment claim.

## 2026-08-29T15:43-0500 · state/policy/telephony/security · Person 2/Codex
Human-approved D30/D-04E: complete canonical playback plus a same-call, operation-bound,
Twilio-signature-verified DTMF challenge is required to transition to `COMMITTED`.
→ Affects: everyone. Early/wrong/missing/late/replayed/invalid events remain `UNKNOWN`;
  verbal/model interpretation is supporting evidence only and cannot commit.

## 2026-08-29T15:41-0500 · policy/realtime/telephony/security · Person 2/Codex
Human-approved D29/D-04D: only trusted deterministic code may render the exact canonical
spoken acceptance; the output model cannot write or alter commitment language.
→ Affects: everyone. First-frame handoff enters execution uncertainty; partial/interrupted
  speech becomes `UNKNOWN`, is never replayed, and needs separately approved confirmation.

## 2026-08-29T15:01-0500 · state/policy/tools/security · Person 2/Codex
Human-approved D28/D-04C: a claimed dispatch never returns to `PREPARED` and is never
automatically resent; lost certainty becomes `UNKNOWN` for query-only reconciliation.
→ Affects: everyone. Enforce one dispatch attempt, monotonic states, conflicting-action
  blocking, and no retry capability for workers, schedulers, operators, models, or cleanup.

## 2026-08-29T14:55-0500 · state/policy/tools/security · Person 2/Codex
Human-approved D27/D-04B: `PREPARED` operations expire after 30 seconds or the earliest
bound evidence validity end, whichever occurs first.
→ Affects: Person 2/3/4. Check expiry atomically on every claim/dispatch; never extend or
  revive an operation, and retain complete final revalidation even inside the TTL.

## 2026-08-29T14:47-0500 · state/policy/tools/security · Person 2/Codex
Human-approved D26/D-04A: binding commitments use exact-payload `PREPARED` operations,
immediate deterministic reauthorization, one idempotent dispatch, and explicit outcomes.
→ Affects: everyone. External adapters require operation-scoped policy capability;
  `UNKNOWN` blocks blind retry/conflicting negotiation and must enter reconciliation.

## 2026-08-29T14:45-0500 · identity/mandate/security · Person 2/Codex
Human-approved D25/D-03C: every mandate write requires a fresh TOTP challenge and an exact-
transaction confirmation that expires after two minutes and is atomically single-use.
→ Affects: Person 2/3/4. Bind actor/session/mandate version/action/payload; reject replay,
  expiry, or substitution, and give voice/model paths no challenge or confirmation capability.

## 2026-08-29T14:44-0500 · identity/mandate/security · Person 2/Codex
Human-approved D24/D-03B: dashboard sign-in uses Supabase email OTP; every mandate write
requires enrolled TOTP/AAL2 plus deterministic transaction confirmation.
→ Affects: everyone. Hackathon scope is USD 0 and pre-authorized team emails only; verify
  JWT/session/owner server-side, keep service-role keys off clients, and retain Volta audit data.

## 2026-08-29T14:42-0500 · mandate/policy/security · Person 2/Codex
Human-approved D23/D-03A: authoritative mandate creation and mutation occur only through
the authenticated dashboard; voice and model paths receive no mandate-write capability.
→ Affects: everyone. Build canonical diff/confirmation and deterministic server checks;
  voice may explain a denial but cannot create drafts, intents, tokens, or mutations.

## 2026-08-29T14:41-0500 · mandate/policy/security · Person 2/Codex
Human-approved D22/D-02P: only the authenticated mandate owner may override RT; lowering
the margin requires rationale, side-by-side risk/USD impact, and separate confirmation.
→ Affects: everyone. Create a new mandate version atomically, audit the exact disclosure
  and actor, and invalidate/re-evaluate every unresolved proposal after a successful change.

## 2026-08-29T14:40-0500 · policy/security · Person 2/Codex
Human-approved D21/D-02O: RT applies no financial floor above zero and no financial cap;
zero and large valid recommendations remain visible for explicit human action.
→ Affects: Person 2/3/4. Do not clamp or hide output; reject technical overflow instead,
  show USD impact/sensitivities/disclosures, and distinguish acceptance from override.

## 2026-08-29T14:38-0500 · policy/security · Person 2/Codex
Human-approved D20/D-02N: RT requires valid rates for every date in the newest complete
250-joint-business-day sequence and exact `i` to `i+h` horizon pairing.
→ Affects: Person 2/3/4. Any gap/duplicate/conflict blocks; never skip, forward-fill,
  interpolate, or permit caller/model data to repair authorization-relevant history.

## 2026-08-29T14:35-0500 · policy/security · Person 2/Codex
Human-approved D19/D-02M: COP uses a versioned Law 51 statutory holiday calendar, manually
cross-checked against official Banco de la República notices, as a banking-day proxy.
→ Affects: Person 2/3/4. Display the proxy limitation, require reviewed annual tables,
  and fail closed for unreviewed years, discrepancies, or exceptional closures.

## 2026-08-29T14:33-0500 · policy/security · Person 2/Codex
Human-approved D18/D-02L: initial RT calendar coverage is limited to official, versioned
USD/COP evidence; every other non-USD currency is unsupported.
→ Affects: Person 2/3/4. COP remains fail-closed until its authoritative calendar source
  is separately reviewed and approved; rate availability never implies calendar support.

## 2026-08-29T14:28-0500 · policy/security · Person 2/Codex
Human-approved D17/D-02K: RT horizons use a versioned joint USD/quotation-currency banking
calendar and count only dates when both relevant banking systems are open.
→ Affects: Person 2/3/4. Unsupported or ambiguous calendar evidence fails closed; never
  infer calendars or accept holiday schedules from callers, carriers, browsers, or models.

## 2026-08-29T14:26-0500 · policy/security · Person 2/Codex
Human-approved D16/D-02J: RT uses a one-indexed nearest-rank percentile without
interpolation, a zero margin floor, and upward basis-point rounding.
→ Affects: Person 2/3/4. Do not use library percentile defaults or binary floating-point;
  preserve ranks/selected values and use the same oracle for displayed sensitivities.

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

## 2026-08-29T14:24-0500 · policy/security · Person 2/Codex
Human-approved D15/D-02I: RT uses exactly the most recent 250 valid daily observations.
→ Affects: Person 2/3/4. Show a mandatory adjacent disclosure that the sample has sparse
  tail evidence, excludes older regimes, cannot predict crises, and does not cap loss.

## 2026-08-29T14:21-0500 · policy/security · Person 2/Codex
Human-approved D14/D-02H: FX authorization requires a primary observation no older than
two hours; covered pairs block above 1% official-source divergence.
→ Affects: Person 2/3/4. Cache approximately hourly, never extend age during outage,
  respect official publication calendars, and label uncovered pairs as not cross-checked.

## 2026-08-29T14:19-0500 · policy/security · Person 2/Codex
Human-approved D13/D-02G: Open Exchange Rates Free is the primary hackathon FX source,
with immutable evidence and pair-appropriate official-source cross-checks.
→ Affects: Person 2/3/4. Treat rates as indicative, keep credentials server-side, reject
  unapproved symbols, and do not authorize until freshness/divergence/outage rules are approved.

## 2026-08-29T14:16-0500 · policy/security · Person 2/Codex
Human-approved D12/D-02F: RT requires 250 valid daily observations, a customer-supplied
1–10-business-day horizon, and a 99th adverse-percentile recommendation.
→ Affects: Person 2/3/4. Show 95th/97.5th/worst sensitivity and limitations; unsupported
  horizons or insufficient data produce no recommendation and cannot authorize non-USD cost.

## 2026-08-29T14:14-0500 · policy/security · Person 2/Codex
Human-approved D11/D-02E: RT uses transparent historical simulation of horizon-matched
adverse FX movements to recommend—but never authorize—a margin.
→ Affects: Person 2/3/4. Preserve replayable source evidence and disclose horizon,
  percentile, worst observation, spread/fees, sensitivity, and historical limitations.

## 2026-08-29T14:11-0500 · domain/policy/security · Person 2/Codex
Human-approved D10/D-02D: an RT calculator may dynamically recommend and explain an FX
safety margin, but only explicit authenticated human acceptance/override sets the mandate.
→ Affects: everyone. RT is deterministic and advisory; preserve methodology and limitations,
  show USD impact, prohibit preselected assent, and fail closed without an accepted margin.

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

## 2026-08-29T13:57-0500 · domain/policy/security · Person 2/Codex
Human-approved D9/D-02A: the mandate cap applies to comprehensive customer-payable
all-in USD cost after required FX conversion and safety margin.
→ Affects: everyone. Itemize and preserve all cost components; unknown, excluded, unnamed,
  or uncapped monetary obligations make the total non-final and cannot be authorized.

## 2026-08-29T13:55-0500 · domain/policy/security · Person 2/Codex
Human-approved D8/D-02C: non-USD authorization requires a mandate-configured FX safety
margin applied to the converted comprehensive all-in USD amount.
→ Affects: everyone. Missing margin fails closed; preserve the snapshot, unbuffered value,
  margin, buffered policy value, and mandate version as evidence.

## 2026-08-29T13:52-0500 · domain/policy/security · Person 2/Codex
Human-approved D7/D-02B: all user mandates and internal policy use USD; explicit foreign
quotes use controlled hybrid FX conversion with immutable, auditable rate snapshots.
→ Affects: everyone. Preserve original currencies, never infer currency from country or
  symbols, never accept caller/model rates, and fail closed without approved usable FX data.

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

## 2026-08-29T13:37-0500 · policy/security · Person 2/Codex
Human-approved D1/D-01: the deterministic reference monitor is Volta's authorization
root of trust; prompts and probabilistic guardrails are defense-in-depth only.
→ Affects: everyone. Every consequential mutation path must prove complete mediation
  against the current authoritative mandate/state and fail closed; import layering alone
  is not sufficient evidence.

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

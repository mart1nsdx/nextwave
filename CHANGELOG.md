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

## 2026-08-29T20:14-0500 · integration · Diego/claude
Integrated the three diverged lines of work onto one branch off `main`: `origin/martin`
(the six policy/evidence/drayage migrations, `seed.sql`, `schema.dbml`) and
`origin/docs/approve-d01-reference-monitor` (the deterministic policy kernel, the
conversation guard, the handoff lifecycle and 45 more tests). Neither contained the other,
and neither was self-consistent alone: the kernel decides against `offers`,
`policy_decisions`, `commitments` and `evidence`, and those tables only existed in the
migrations on `martin`. Suite goes 41 passed / 2 skipped → **92 passed / 0 skipped**; the
two scaffolded skips in `test_policy.py` and `test_ugly_cases.py` are now real tests.
Conflicts were documentation only and nothing was dropped: CHANGELOG entries from both
sides interleaved by timestamp, and `docs/DECISION_LOG.md` keeps D1–D8 plus D-DB-01..04
with Person 2's 67 decisions moved whole into `docs/DECISION_LOG_SECURITY.md`, indexed by
which ones have code behind them.
→ Affects: everyone. `main` had neither the policy engine nor the schema, so anything built
  on `main` today was building against tables and an authorization layer it could not see.
  Rebase onto this before continuing.

## 2026-08-29T19:47-0500 · integration/voice/tools/policy/evidence/handoff · Person 2/Codex
Merged current main into the Person 2 branch and integrated deterministic conversational mediation
with main's persisted transcript/recap callbacks, audited handoff lifecycle, updated VAD, configuration,
domain exports, and Supabase contracts. Converted main's production handoff speech to English.
→ Affects: everyone. The same current VoiceSession now records both sides, triggers one handoff, measures
  latency, and policy-mediates quote/model output. All historical changelog and ugly-case entries remain.

## 2026-08-29T19:31-0500 · tools/voice/policy/security · Person 2/Codex
Expanded the English policy-mediated demo with stateful deterministic extraction for spoken-number
money, ISO/named currencies, itemized costs, pickup date, equipment, quote validity, and session-bound
carrier identity, plus broader binding-language output containment.
→ Affects: voice/demo/security. Missing or ambiguous facts produce fixed clarification; foreign
  currency requires an injected immutable FX snapshot and approved mandate margin; no live FX source,
  persistence, real identity provider, or universal semantic paraphrase classifier was added.

## 2026-08-29T19:16-0500 · voice/agent/tools/policy/security · Person 2/Codex
Converted the complete demo profile, scenarios, and spoken behavior to English and connected the
live conversation loop to deterministic policy mediation through the approved tools boundary.
→ Affects: voice/demo/security. Explicit numeric USD offers are evaluated before the model; an
  over-cap offer or false caller authority claim produces a fixed escalation and cannot become an
  acceptance. This is a narrow demo adapter, not comprehensive natural-language quote extraction.

## 2026-08-29T19:12-05 · scripts · Martin/claude
`award_from_recaps.py --commit --sms` now texts the negotiation specs (carrier, container,
tarifa, ventana, condiciones) to the awarded carrier's `counterparty_contacts.phone` via
Twilio — and to no one else. `--sms` requires `--commit`; a Twilio/credential failure is
reported, never fatal. The SMS body + result land in the JSON artifact.
→ Affects: nobody. Uses the existing TWILIO_* creds in backend/.env.

## 2026-08-29T19:05-0500 · agent/voice/security · Person 2/Codex
Added deterministic speech-duration budgeting and an exact-match precompiled pickup-date fact for
short common answers; unmatched dates remain untouched and exact safety recaps are never truncated.
→ Affects: voice/demo/security. One live-LLM fake-transport sample observed 953.7 ms first audio,
  1,299.2 ms completion, 10 words and ~4.0 seconds speech; real PSTN/TTS evidence remains NOT RUN.

## 2026-08-29T19:03-05 · scripts · Martin/claude
`award_from_recaps.py` now scopes strictly to one container / RFQ: it only compares
carrier calls tied to that RFQ and excludes any other recap as noise. A call is tied by
`call_cases.metadata->>'rfq_id'`, by an `offers` row, or by `--assign` (which `--commit`
persists into `call_cases.metadata` as `{rfq_id, operation_ref, counterparty_id,
container_number}`). If nothing is tied, it refuses rather than guessing.
→ Affects: whoever wires the live outbound-call path — stamp those same
  `call_cases.metadata` keys when the agent dials a carrier for an operation, so the
  post-call comparison needs no manual `--assign`.

## 2026-08-29T18:57-0500 · voice/agent/observability/security · Person 2/Codex
Added evidence-labeled sentence latency telemetry (STT endpoint, model first chunk, TTS first audio,
end-to-end, completion and barge-in), CLI median/p95/max summaries, shorter streaming chunks, and a
compiled runtime prompt under half the canonical prompt size without removing security controls.
→ Affects: voice/security/demo. One live-LLM fake-transport sample observed 1,154.1 ms first audio;
  this is not PSTN evidence. Keep authorization in policy; collect 20+ live turns before claims.

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

## 2026-08-29T18:09-0500 · domain/policy/tools/agent/security · Person 2/Codex
Implemented the first executable deterministic security kernel: immutable mandates/proposals/FX
evidence, comprehensive buffered USD evaluation, reason-coded fail-closed decisions, exact recap
evidence, deterministic ranking, idempotent proposal tools, and a 30-second single-use commitment
claim. Preserved the partners' cascade/personality while correcting commitment wording.
→ Affects: everyone. Models receive proposal-only authority; external adapters must consume only a
  freshly revalidated server claim. No live calls/email/payment were run; provider integration,
  persistent repository adapters, dashboard authorization, and live/manual evidence remain pending.

## 2026-08-29T18:09-05 · voice, config · Codex
Raised the local barge-in gate from 900 RMS for 120 ms to 1800 RMS for 300 ms and added
a regression test for sustained moderate background noise.
→ Affects: anyone testing calls. Restart the backend after pulling; tune the two
  `VAD_BARGE_IN_*` variables only if the actual phone line still needs calibration.

## 2026-08-29T17:45-0500 · docs/architecture/security · Person 2/Codex
Published the 30-page `VOLTA_SECURITY_POLICY_ARCHITECTURE.pdf`: one-sentence summary, complete
plain-language flow, eight vector flow diagrams, controls, schedule, costs, D1-D63 index and sources.
→ Affects: everyone. Use the PDF for onboarding and review; the decision log remains authoritative,
  implementation is still blocked by official rules, and all product verification remains NOT RUN.

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


## 2026-08-29T17:29-0500 · architecture/policy/security · Person 2/Codex
Human blanket-approved recommended D51-D63 and the Person 2 architecture baseline: callback bounds,
one-use revalidation, exact tools, escalation/injection, crypto, observability/model, red team,
release/repo gates, competition-rule block, final claims, and the H0-H24 delivery schedule.
→ Affects: everyone. Read `docs/PERSON2_ARCHITECTURE_BASELINE.md`; implementation remains blocked
  pending official competition rules, and every listed verification remains NOT RUN.

## 2026-08-29T17:22-0500 · voice/identity/policy/security · Person 2/Codex
Human-approved D50/D-11A: an inbound order number is lookup evidence only; protected processing
requires a new outbound call to the carrier number in the verified directory.
→ Affects: Person 1/2/3. Reveal nothing on the inbound leg, resolve destinations from trusted state,
  bind a single-use callback challenge, fail closed on call ambiguity, and meter all USD call costs.

## 2026-08-29T17:20-0500 · crypto/infra/security · Person 2/Codex
Human-approved D49/D-14B: use loopback-only OpenBao Transit dev mode as the USD 0 demo key
provider, only for synthetic/explicit demo data and never for staging or production.
→ Affects: Person 2/3. Pin the artifact, protect ephemeral tokens, fail closed on restart/key loss,
  block non-loopback/production use, disclose limitations, and never claim production-grade custody.

## 2026-08-29T17:18-0500 · crypto/data/security · Person 2/Codex
Human-approved D48/D-14A: encrypt restricted content with application-level envelope encryption
behind a replaceable key-provider boundary; demo incremental spend is fixed at USD 0.
→ Affects: Person 2/3/4. Store ciphertext/wrapped DEKs only, bind tenant/record/purpose in AAD,
  fail closed on key errors, label demo custody non-production, and block it in production mode.

## 2026-08-29T17:15-0500 · domain/data/security · Person 2/Codex
Human-approved D47/D-12A: classify all data as `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, or
`RESTRICTED`; composites inherit the highest source class and unknown fields fail restricted.
→ Affects: everyone. Enforce labels at every disclosure boundary, minimize model inputs, omit
  protected bodies before logging, and never let model/customer labels declassify authoritative data.

## 2026-08-29T17:12-0500 · data/storage/security · Person 2/Codex
Human-approved D46/D-13E: expired transcripts become inaccessible and leave every active system
within 24 hours; backup remnants must expire within 30 additional days.
→ Affects: Person 2/3/4. Inventory every copy, apply deletion tombstones before restored data is
  queryable, prohibit resurrection, monitor both deadlines, and treat overruns as control failures.

## 2026-08-29T17:11-0500 · identity/data/security · Person 2/Codex
Human-approved D45/D-13D: fresh TOTP opens a fixed, non-renewable five-minute transcript-viewing
session bound to the same actor, tenant, authenticated browser session, and audit purpose.
→ Affects: Person 2/3/4. Reauthorize every body read, invalidate on authority/security changes,
  enforce expiry with server time, audit use, and grant no download/export/model capability.

## 2026-08-29T17:08-0500 · identity/data/security · Person 2/Codex
Human-approved D44/D-13C: transcript bodies are restricted to the tenant owner or explicitly
assigned auditor/security role, with fresh TOTP and an audit event for every access attempt.
→ Affects: Person 2/3/4. Separate body from metadata, deny models/ordinary operators, prevent
  snippets and cache leakage, reauthorize each request, and keep bulk export disabled.

## 2026-08-29T17:03-0500 · voice/data/security · Person 2/Codex
Human-approved D43/D-13B: play a deterministic notice that calls are monitored and transcribed
for audit, with transcripts retained one year; do not ask for or infer consent.
→ Affects: Person 1/2/3. Never call this audio recording, prevent notice bypass, record delivery
  evidence, and block unsupported jurisdictions pending applicable legal review.

## 2026-08-29T16:59-0500 · voice/data/security · Person 2/Codex
Human-approved D42/D-13A: Volta stores transcripts and linked audit metadata for one year,
but captures and stores no call audio.
→ Affects: everyone. Do not enable provider recording or duplicate transcript bodies into logs;
  preserve transcript uncertainty, enforce expiry/deletion, and keep access/crypto/consent pending.

## 2026-08-29T16:54-0500 · voice/domain/policy/security · Person 2/Codex
Human-approved D41/D-04P: carrier confirmation is verbal but accepted only by deterministic
gates bound to the exact complete recap version and anchored call evidence.
→ Affects: Person 1/2/3. Treat model output as a four-value proposal, reject stale/corrective/
  ambiguous assent, allow one clarification, and keep confirmation non-binding under D31.

## 2026-08-29T16:51-0500 · notify/policy/security · Person 2/Codex
Human-approved D40/D-04O: protect 50 Resend messages/day and 1,500/month exclusively for
official commitments; challenges and recaps share only the unreserved half.
→ Affects: Person 2/3/4. Reserve atomically across total/class periods, never let lower-priority
  traffic borrow, count ambiguous sends conservatively, and never auto-upgrade or fail over.

## 2026-08-29T16:49-0500 · mandate/dashboard/policy/security · Person 2/Codex
Human-approved D39/D-04N: `commitment_mode` is an explicit unselected field on each operation
mandate; it has no account default, template authority, or inheritance from prior work.
→ Affects: everyone. Creation/change requires D23–D25; changes version the mandate, invalidate
  pending authorization, never dispatch immediately, and preserve in-flight unknown evidence.

## 2026-08-29T16:47-0500 · identity/dashboard/policy/security · Person 2/Codex
Human-approved D38/D-04M: each `HUMAN_ESCALATION` commitment requires fresh TOTP and a
two-minute, single-use approval bound to the exact winner, evidence, recipient, and email.
→ Affects: everyone. Display all material terms/alternatives, invalidate on any change,
  authorize only one D28 dispatch, and give voice/model/email/admin paths no approval capability.

## 2026-08-29T16:45-0500 · identity/notify/security · Person 2/Codex
Human-approved D37/D-04L: carrier mailbox challenges expire after 15 minutes, are single-use,
and have one active token per contact; replacement permanently invalidates the prior token.
→ Affects: Person 2/3/4. Enforce three/contact/hour and ten/tenant/day issuance limits,
  atomic consumption, hashed tokens, generic errors, and no authority/terms in verification.

## 2026-08-29T16:43-0500 · identity/notify/policy/security · Person 2/Codex
Human-approved D36/D-04K: recap/commitment recipients resolve only from a versioned carrier
directory; new/changed contacts need owner approval plus a mailbox-control challenge.
→ Affects: everyone. Model/call addresses are proposals only; send by verified contact ID/version,
  recheck before dispatch, prevent header injection, support revocation, and isolate tenants.

## 2026-08-29T16:38-0500 · notify/identity/security · Person 2/Codex
Human-approved D35/D-04J: carrier-facing Resend email uses an existing team-controlled
domain or delegated subdomain; the exact domain remains unresolved and must not be invented.
→ Affects: Person 2/3/4. Verify ownership and SPF/DKIM/DMARC independently, isolate DNS
  changes, allowlist headers, and fail closed until production identity is approved.

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

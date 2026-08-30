# Verification & commitment notification

The slice of Volta that turns a phone call into **auditable evidence** and a post-call
**recap + brief**. It does not decide anything — it produces the record a later policy
step reads before a commitment could reach `COMMITTED`.

> Speech is probabilistic. Authority is deterministic. This module only *records and
> reports*; `policy/` (another module) *authorizes*.

**Read "What is not built yet" before quoting anything from this file.** Every path below
either points at a file and route that exist today, or is marked `NOT BUILT`. Nothing here
is aspirational without that label.

## Flow — what actually runs today

```text
Twilio number ──POST /twilio/voice──► TwiML <Connect><Stream url="wss://…/twilio/media">
                                       │   and store.open_case() writes the call_cases row
                 WSS /twilio/media ────┤   mu-law 8 kHz, INBOUND (caller) track only
                                       ▼
                       voice/session.py  VoiceSession — four concurrent jobs
                        ├─ STT: Deepgram live (nova-3, language=multi)  → caller finals
                        ├─ LLM: OpenAI Agents SDK                       → reply text
                        ├─ TTS: Deepgram aura-2                         → audio back down
                        │        the same socket; barge-in sends `clear`
                        ▼
              on_final_transcript  ==  persist_final() closure in app/main.py
                        │   caller finals  → track=inbound,  speaker=caller
                        │   agent replies  → track=outbound, speaker=agent (generated text)
                        ▼
        ledger/evidence.py EvidenceLedger.record_segment
                        └─► repo/store.py ─► Supabase  call_transcript_events
                                             (upsert on event_key, ignore_duplicates)

  POST /twilio/status (completed | failed | busy | no-answer | canceled)
  ── or the media WebSocket closing, whichever fires first; both go through
     finalize_call(), deduplicated by telephony/idempotency.py SeenEvents
                        ▼
        RecapService.run  (app/main.py — the composition root, not a package)
          ├─ ledger.transcript_text(call_sid)      — empty transcript ⇒ no recap, warn
          ├─ agent.build_recap  + agent.build_brief (OpenAI, structured output)
          └─ store.save_recap / store.save_brief   — Supabase call_recaps / call_briefs
                        ▼
        GET /calls · /calls/{sid}/transcript · /recap · /brief
```

## The agent's own track is generated text, not STT evidence

`<Connect><Stream>` is bidirectional — which is the only reason barge-in works, because we
can send `clear` down the socket and cut the agent off mid-sentence (`telephony/twiml.py`
says so in its module docstring). The trade-off is that a `<Connect>` stream delivers the
**inbound track only**: Twilio never sends back the audio it played to the caller.

So the `track=outbound / speaker=agent` rows in `call_transcript_events` are **the text the
agent handed to the synthesizer**, recorded by `VoiceSession._respond`, anchored to the
`offset_ms` of the caller turn it answers. They are not a transcription of what the caller
heard. Two consequences that must not be forgotten when this evidence is read:

- The outbound `audio_offset_ms` is **the inbound turn's offset**, not the moment the agent
  spoke. Inbound and outbound offsets share a clock but mean different things.
- On an interruption, only the text already passed to TTS is recorded (`_respond`'s
  `CancelledError` branch). The caller may have heard **less** than the record shows, never
  more — deliberately, so the agent can never later claim it said something the other side
  never got.

This is a defensible design, not an oversight, but it means the outbound track is weaker
evidence than the inbound track and must never be presented as "what was said on the line".
If true both-track audio evidence is ever needed, that is a `<Start><Stream
track="both_tracks">` recording leg **in addition to** the `<Connect>` stream — not a
replacement for it, because switching to `<Start>` would delete barge-in.

## File map

The import graph is one-directional and enforced by `backend/tests/test_layering.py`. The
"may import" column is copied from that test's `ALLOWED` dict — the dict is the contract;
this table is only a reader's index of it.

| Function | File(s) | May import (from `ALLOWED`) |
| --- | --- | --- |
| Call transport: Twilio webhooks, Media Streams, TwiML, outbound dial, warm transfer | `app/telephony/router.py`, `stream.py`, `twiml.py`, `outbound.py`, `handoff.py`, `idempotency.py` | `domain`, `config`, `voice` |
| Voice pipeline: turn loop, VAD/barge-in, STT, TTS, latency | `app/voice/session.py`, `vad.py`, `frames.py`, `events.py`, `llm.py`, `latency.py`, `speech_budget.py`, `stt/deepgram.py`, `tts/deepgram.py` | `domain`, `config`, `agent`, `tools` |
| Persistence (Supabase; the only DB client in the codebase) | `app/repo/store.py` | `domain`, `config` |
| Evidence log (append-only, `event_key`, `has_audio_anchor`) | `app/ledger/evidence.py` | `domain`, `repo` |
| Recap + brief generation (OpenAI, structured output) | `app/agent/recap.py`, `models.py`, `prompts.py`, `context.py` | `domain` |
| Recap email (SendGrid) + rendering | `app/notify/sender.py`, `app/notify/render.py` | `domain`, `config` |
| Deterministic authorization | `app/policy/engine.py`, `app/policy/handoff.py` | `domain` |
| Model-facing tool surface | `app/tools/security.py`, `handoff.py`, `conversation_guard.py` | `domain`, `policy`, `repo`, `ledger`, `market`, `notify` |
| Shared types + the Protocols that decouple the above | `app/domain/models.py`, `app/domain/ports.py` | — (leaf) |
| Settings — the only reader of the environment | `app/config.py` | — (leaf) |
| Wiring — the only place the pieces meet (`RecapService`) | `app/main.py` | unrestricted (composition root) |

The seams: `telephony/router.py` receives a `TranscriptStore` (Protocol) and async callbacks
injected by `main.py`; `voice/session.py` receives an `on_final_transcript` sink rather than
a store, so it never touches persistence; `agent/` receives a `RecapModel`. No outer layer
imports an inner one.

An earlier version of this document mapped two files that do not exist: a `realtime`
package with a transcriber in it, and a separate Twilio-named router module under
`app/telephony/`. The `realtime` package was renamed `voice/` (see `docs/DECISION_LOG.md`),
its Deepgram adapter is `app/voice/stt/deepgram.py`, and the Twilio edge is the single
`app/telephony/router.py` above.

## What is not built yet

Listed so no gate above is read as if it were enforced.

| Claim you might expect | Reality | Item |
| --- | --- | --- |
| The recap is emailed to the counterparty | `NOT BUILT`. `RecapService` (`app/main.py`) constructs no sender and never calls `set_recap_delivery`. `SendGridRecapSender` / `NullRecapSender` exist in `app/notify/sender.py` and are exercised **only** by `backend/tests/test_notify.py`; nothing in the running app imports them. | — |
| `GET /calls/{sid}/recap-delivery` | `NOT BUILT`. Planned as work item **W4**. The `call_recap_deliveries` table exists and `store.set_recap_delivery` / `get_recap_delivery` are implemented on both stores, but no route and no caller exist. | W4 |
| `recap_delivery.status = 'sent'` gates `RECAP_SENT → COMMITTED` | `NOT BUILT` on both sides. No delivery row is ever written, and `app/policy/` contains no state machine — it exports `evaluate_quote`, `require_preagreement_evidence`, `select_best`, `handoff_is_authorized` and nothing else. `COMMITTED` appears in the codebase only inside docstrings. | — |
| `ledger.has_audio_anchor` is the check behind `EVIDENCE_MISSING` | Half true. The function exists and `backend/tests/test_ledger.py` covers it, but no production caller invokes it. The `EVIDENCE_MISSING` outcome that *is* wired comes from `policy.require_preagreement_evidence`, which reads `carrier_confirmed_exact_recap` / `confirmed_at` / `transcript_anchor_ms` off the proposal. | — |
| Twilio webhook signatures are validated | `NOT BUILT`. `TWILIO_AUTH_TOKEN` and `VALIDATE_TWILIO_SIGNATURE` are read into `Settings`, but no code constructs a `RequestValidator` or checks `X-Twilio-Signature`. The setting is inert today. | separate item |
| `app/market/` orchestrates the RFQ | `NOT BUILT`. `app/market/__init__.py` is nine lines of docstring and no code. Award-by-analysis lives in `backend/scripts/award_from_recaps.py`, which is deliberately analysis-only (`DECISION_LOG.md` D71). | — |

## Environment variables

All env access is in `app/config.py` (the only reader). Template: `backend/.env.example`.
The two agree; if you add a key, add it to both.

| Key | Purpose |
| --- | --- |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_PHONE_NUMBER` | Outbound dial (`telephony/outbound.py`). The auth token is *not* yet used for signature checks — see above |
| `VALIDATE_TWILIO_SIGNATURE` | Read but unused today |
| `OPENAI_API_KEY` / `OPENAI_AGENT_MODEL` | The live conversational agent |
| `OPENAI_REASONING_EFFORT` / `OPENAI_MAX_OUTPUT_TOKENS` | Latency budget for the live turn |
| `OPENAI_RECAP_MODEL` | Recap + brief model; falls back to `OPENAI_AGENT_MODEL` |
| `DEEPGRAM_API_KEY` | Both STT and TTS |
| `STT_PROVIDER` / `STT_MODEL` / `STT_LANGUAGE` | Live recognition (`deepgram` or `fake`) |
| `DEEPGRAM_MODEL` / `DEEPGRAM_LANGUAGE` | Aliases for the evidence path; default to the live STT values |
| `TTS_PROVIDER` / `TTS_MODEL` | Synthesis (`deepgram` or `fake`) |
| `VAD_*` (seven keys) | Turn end vs barge-in — two questions answered by two mechanisms; see `voice/vad.py` |
| `SUPABASE_URL` / `SUPABASE_SECRET_KEY` | Evidence store (secret key, backend only) |
| `ESCALATION_PHONE_NUMBER` | Who gets dialled on a warm transfer |
| `SENDGRID_API_KEY` / `RECAP_FROM_EMAIL` / `RECAP_FROM_NAME` / `RECAP_TO_EMAIL` | Recap email. **Configured but not wired** — see "What is not built yet" |
| `PUBLIC_BASE_URL` | Public HTTPS domain Twilio calls back into (ngrok URL). Empty raises at stream-URL construction rather than failing silently |

There is no `FORWARD_TO_NUMBER`; an earlier version of this file listed one.

Without `SUPABASE_URL` + `SUPABASE_SECRET_KEY` the app falls back to
`InMemoryTranscriptStore` and logs `supabase_unconfigured_using_memory_store` — nothing is
persisted.

## Supabase

`supabase/migrations/` is the source of truth. Four files, applied in order:

1. `20260829125514_create_call_transcripts.sql` — `call_cases`, `call_transcript_events`
2. `20260829133007_add_call_numbers_and_recap.sql` — `call_cases.from_number/to_number`,
   `call_recaps`, `call_briefs`, `call_recap_deliveries`
3. `20260829222248_agreement_candidates.sql` — `call_recaps.agreement_candidates` (jsonb array)
4. `20260829232900_add_call_handoffs.sql` — `call_handoffs` (one active transfer per case)

Apply — pick one:

- **CLI:** `supabase login` → `supabase link --project-ref <ref>` (`<ref>` is the segment
  after `/project/` in the dashboard URL) → `supabase db push`
- **Manual:** paste the `.sql` files into the dashboard SQL Editor, in order

RLS is enabled on every table with no policies: the secret key (backend) bypasses it; a
browser client with the anon key is blocked. Dashboard reads must go through the API below,
never a direct client.

`call_transcript_events` carries **two** idempotency mechanisms: `event_key text not null
unique` (what `repo/store.py` upserts on, with `ignore_duplicates=True`) and a separate
`unique (case_id, track, sequence_number)`. See `DECISION_LOG.md` D72 for why the
sequence-number half is proposed for removal.

## HTTP API — every route that exists

From `app/telephony/router.py` and `app/main.py`. No others are mounted.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness |
| POST | `/twilio/voice` | Inbound webhook → TwiML `<Connect><Stream>`; opens the case |
| WS | `/twilio/media` | Media Streams socket: caller audio in, TTS audio out, `clear` on barge-in |
| POST | `/twilio/status` | Call status callback. `completed`/`failed`/`busy`/`no-answer`/`canceled` finalizes the case and triggers the recap. Deduplicated per `CallSid:CallStatus`; returns 204 |
| POST | `/twilio/voice/echo` | Loopback TwiML — audio-path smoke test |
| WS | `/twilio/media/echo` | Loopback socket for the same |
| POST | `/twilio/handoff/{id}/wait` | Hold loop played to the carrier while a human is dialled |
| POST | `/twilio/handoff/{id}/brief` | Private briefing to the operator; DTMF gather |
| POST | `/twilio/handoff/{id}/accept` | DTMF `1` joins the conference; anything else fails the handoff |
| POST | `/twilio/handoff/{id}/operator-status` | Operator leg status → `HANDOFF_FAILED` when unanswered |
| POST | `/twilio/handoff/{id}/conference` | Conference status callback → `COMPLETED` on `conference-end` |
| POST | `/calls` | Place an outbound call. Body `{"to": "+E164"}`; 503 if Twilio is unconfigured |
| GET | `/calls?limit=50` | Recent cases |
| GET | `/calls/{sid}/transcript` | Ordered transcript events; 404 if the case is unknown |
| GET | `/calls/{sid}/recap` | The negotiation summary; 404 until generated |
| GET | `/calls/{sid}/brief` | Structured actions + mentions; 404 until generated |
| POST | `/calls/{sid}/recap` | Regenerate the recap and brief. **No `to_email` parameter and no send** — it only rewrites the stored rows. 409 if there is no transcript |

There is no `POST /twilio/call-status` and no `POST /twilio/stream-status`; an earlier
version of this file documented both. The status callback is `POST /twilio/status`.

## Runbook

```bash
cd backend
uv sync
cp .env.example .env          # fill it

# offline — replay a scenario through the whole voice pipeline (no PSTN, no cost):
uv run python -m scripts.sim_call --scenario boss_approved
# scenarios: hello, boss_approved, ambiguous_amount, spoken_over_cap,
#            quote_components, foreign_no_fx, interrupts
# --live-llm uses the real model with fake STT/TTS

# live:
uv run uvicorn app.main:app --reload --port 8000
ngrok http 8000               # set PUBLIC_BASE_URL to the https URL
```

In the Twilio Console, point the number's **voice webhook** at
`https://<domain>/twilio/voice` and its **call status callback** at
`https://<domain>/twilio/status`. The ngrok URL changes on every restart — re-point both.
(`backend/scripts/point_number.py` does this from the CLI.)

Before pushing: `uv run ruff check . && uv run mypy app/ && uv run pytest` — all green.

## Out of scope (other modules)

- `policy/` — deterministic authorization. Today: quote evaluation, pre-agreement evidence,
  best-offer selection, handoff authorization. The `HEARD → … → COMMITTED` state machine
  does not exist yet.
- `market/` — RFQ orchestration. Docstring only.
- Wiring the `dashboard/` screens to the read API above.

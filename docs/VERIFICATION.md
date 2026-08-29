# Verification & commitment notification

The slice of Volta that turns a phone call into **auditable evidence** and a **written
recap** the counterparty receives by email. It does not decide anything — it produces the
record a later policy step reads before a commitment can reach `COMMITTED`.

> Speech is probabilistic. Authority is deterministic. This module only *records and
> reports*; `policy/` (another module) *authorizes*.

## Flow

```text
Twilio number ──POST /twilio/voice──► TwiML <Start><Stream track="both_tracks">
                                       │                     (opens the call_cases row)
                 WSS /twilio/media ────┤  mu-law 8 kHz frames, per track, forwarded raw
                                       ▼
                     Deepgram streaming STT  (nova-3, language=multi)
                                       │  Results / is_final=true / start=<seconds>
                                       ▼
        ledger  ──►  Supabase   call_transcript_events   (append-only, audio offset,
                                       │                   idempotency key)
        POST /twilio/call-status (CallStatus=completed)
                                       ▼
                      RecapService  (composition root)
                       ├─ read transcript from Supabase
                       ├─ agent.build_recap  + agent.build_brief   (OpenAI, structured)
                       ├─ notify.SendGridRecapSender  ──► email to counterparty
                       └─ persist recap / brief / delivery status  ──► Supabase
                                       ▼
        GET /calls/{sid}/transcript · /recap · /brief · /recap-delivery
```

`recap_delivery.status = 'sent'` is the gate `RECAP_SENT → COMMITTED` waits on.
`ledger.has_audio_anchor(call_sid)` is the check behind `EVIDENCE_MISSING`.

## File map — one function per file, nothing coupled

The import graph is one-directional and enforced by `backend/tests/test_layering.py`.

| Function | File(s) | Does **not** import |
| --- | --- | --- |
| Call transport (Twilio webhooks, Media Streams, TwiML, signature) | `app/telephony/twilio_router.py` | repo, ledger, agent, notify |
| Transcription (Deepgram live session, one per audio track) | `app/realtime/transcriber.py` | repo, ledger |
| Persistence (Supabase; the only DB client in the codebase) | `app/repo/store.py` | agent, notify, telephony, realtime |
| Evidence log (append-only, `event_key`, `has_audio_anchor`) | `app/ledger/evidence.py` | agent, notify, telephony, realtime |
| Recap + brief generation (OpenAI, structured output) | `app/agent/recap.py`, `app/agent/models.py`, `app/agent/prompts.py` | repo, ledger, notify, telephony |
| Recap email (SendGrid) + rendering | `app/notify/sender.py`, `app/notify/render.py` | repo, ledger, agent, telephony |
| Shared types + the Protocols that decouple the above | `app/domain/models.py`, `app/domain/ports.py` | everything (leaf) |
| Wiring — the only place the pieces meet (`RecapService`) | `app/main.py` | — (composition root) |

The seams: `telephony/` and `realtime/` receive a `TranscriptStore` (Protocol) injected
by `main.py`; `agent/` receives a `RecapModel`; `RecapService` receives a `RecapSender`.
No outer layer imports an inner one.

## Environment variables

All env access is in `app/config.py` (the only reader). Template: `backend/.env.example`.

| Key | Purpose |
| --- | --- |
| `TWILIO_AUTH_TOKEN` | Validate inbound webhook signatures |
| `FORWARD_TO_NUMBER` | Optional — bridge the inbound call so both legs have audio |
| `VALIDATE_TWILIO_SIGNATURE` | `false` only against a local tunnel |
| `DEEPGRAM_API_KEY` / `DEEPGRAM_MODEL` / `DEEPGRAM_LANGUAGE` | Streaming STT (`nova-3`, `multi`) |
| `OPENAI_API_KEY` / `OPENAI_RECAP_MODEL` | Recap + brief chat model (`gpt-5.6`) |
| `SENDGRID_API_KEY` / `RECAP_FROM_EMAIL` / `RECAP_FROM_NAME` / `RECAP_TO_EMAIL` | Recap email; `RECAP_FROM_EMAIL` must be a verified SendGrid sender |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | Evidence store (service-role key, backend only) |
| `PUBLIC_BASE_URL` | Public HTTPS domain Twilio calls back into (ngrok URL) |

Without `SUPABASE_*` the app falls back to an in-memory store (nothing persisted). Without
`SENDGRID_API_KEY` + `RECAP_FROM_EMAIL` the recap email is disabled (`NullRecapSender`).

## Supabase

`supabase/migrations/` is the source of truth. Two files, applied in order:

1. `20260829125514_create_call_transcripts.sql` — `call_cases`, `call_transcript_events`
2. `20260829133007_add_call_numbers_and_recap.sql` — `call_cases.from_number/to_number`,
   `call_recaps`, `call_briefs`, `call_recap_deliveries`

Apply — pick one:

- **CLI:** `brew install supabase/tap/supabase` → `supabase login` → `supabase link
  --project-ref <ref>` (`<ref>` is the segment after `/project/` in the dashboard URL) →
  `supabase db push`
- **Manual:** paste both `.sql` files into the dashboard SQL Editor, in order

RLS is enabled on every table with no policies: the service-role key (backend) bypasses
it; a browser client with the anon key is blocked. Dashboard reads must go through the
API below, never a direct client.

## HTTP API

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/twilio/voice` | Inbound webhook → TwiML `<Stream>`, opens the case |
| WS | `/twilio/media` | Media Streams receiver → Deepgram |
| POST | `/twilio/stream-status` | Media Stream lifecycle events (logged) |
| POST | `/twilio/call-status` | `CallStatus=completed` → triggers `RecapService` |
| GET | `/calls` | Recent calls |
| GET | `/calls/{sid}/transcript` | Ordered transcript events |
| GET | `/calls/{sid}/recap` | The negotiation summary |
| GET | `/calls/{sid}/brief` | Structured actions + mentions |
| GET | `/calls/{sid}/recap-delivery` | Email delivery status |
| POST | `/calls/{sid}/recap?to_email=…` | Regenerate + resend the recap |

## Runbook

```bash
cd backend
uv sync
cp .env.example .env          # fill it

# offline — replay a transcript fixture through the recap path (no PSTN, no Twilio):
uv run python -m scripts.sim_call --scenario manzanillo_guadalajara

# live:
uv run uvicorn app.main:app --reload --port 8000
ngrok http 8000               # set PUBLIC_BASE_URL to the https URL
```

In the Twilio Console, point the number's **voice webhook** at
`https://<domain>/twilio/voice` and its **call status callback** at
`https://<domain>/twilio/call-status`. The ngrok URL changes on every restart — re-point
both.

Before pushing: `uv run ruff check . && uv run mypy app/ && uv run pytest` — all green.

## Out of scope (other modules)

- `policy/` — the `HEARD → … → COMMITTED` state machine and the `RECAP_SENT` /
  `EVIDENCE_MISSING` checks. This module supplies the evidence they read.
- Outbound calls, the live voice agent (`realtime/` conversational session), RFQ /
  market (`market/`), the model's function-calling surface (`tools/`).
- Wiring the `dashboard/` screens to the read API above.

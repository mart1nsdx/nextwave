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

## 2026-08-29T14:10-0500 · domain, repo, ledger, agent, notify, realtime, telephony, main, supabase · Martin/claude
Built the call-evidence → recap → email path and folded the standalone `apps/voice`
service into `backend/app/` under the layering contract (`apps/voice/`, root
`requirements.txt` and root `.env.example` deleted).
- `domain/`: `CallCase`, `TranscriptEvent`, `Recap`, `CallBrief`, `RecapDelivery`, enums,
  and the `TranscriptStore` / `RecapModel` / `RecapSender` / `TranscriptSink` /
  `CallCompletedHook` ports.
- `repo/`: `SupabaseTranscriptStore` + `InMemoryTranscriptStore` (idempotent upserts).
- `ledger/`: `EvidenceLedger` — append-only, deterministic `event_key`, `has_audio_anchor`.
- `realtime/`: `RealtimeTranscriber` over **Deepgram** streaming STT (`nova-3`,
  `language=multi`) — takes Twilio mu-law 8 kHz raw, no transcode. Persistence is an
  injected sink; realtime/ and telephony/ never import repo/ or ledger/.
- `agent/`: `build_recap` / `build_brief` + `OpenAIRecapModel` (chat, structured outputs).
- `notify/`: `SendGridRecapSender` (Twilio Email) + `NullRecapSender`; renders the recap
  to a Spanish email. A send failure is `RecapDelivery(status=failed)`, never an exception.
- `telephony/`: `create_twilio_router` — `/twilio/voice|media|stream-status|call-status`,
  signature validation, idempotent handlers.
- `main.py`: wiring + `RecapService` (recap → brief → email → persist delivery) + read API
  (`GET /calls`, `/calls/{sid}/transcript|recap|brief|recap-delivery`, `POST /calls/{sid}/recap`).
- New migration `20260829133007_add_call_numbers_and_recap.sql`: `call_cases.from_number/to_number`,
  tables `call_recaps` / `call_briefs` / `call_recap_deliveries`. The prior migration is untouched.
- Deps: `python-multipart` (FastAPI form parsing).
- `config.py` now scoped to this path: added `DEEPGRAM_*`, `OPENAI_RECAP_MODEL`,
  `SENDGRID_API_KEY`, `RECAP_FROM_EMAIL/NAME`, `RECAP_TO_EMAIL`, `FORWARD_TO_NUMBER`,
  `VALIDATE_TWILIO_SIGNATURE`; **removed the unused `twilio_account_sid`,
  `twilio_phone_number`, `openai_realtime_model`, `escalation_phone_number`** — re-add
  them here when the outbound-call / voice-agent / escalation paths need them.
- Docs: new `docs/VERIFICATION.md` is the single reference for this path (design, file
  map, env vars, Supabase, API, runbook). `supabase/README.md` folded into it and
  deleted; `DECISION_LOG.md` D7 tightened, D8 removed.
→ Affects: everyone. `policy/` unchanged — this layer *produces* the evidence
  (`ledger.has_audio_anchor`, stored recap, `call_recap_deliveries.status='sent'`) that the
  `RECAP_SENT → COMMITTED` / `EVIDENCE_MISSING` checks read. Dashboard: read endpoints live.
  Run `supabase db push` for the new migration; `uv sync` for `python-multipart`.

## 2026-08-29T13:40-0500 · verification/notify · martin/Codex
Recorded the real-time evidence, OpenAI transcription, post-call recap, notification,
and dashboard authority boundaries in `docs/DECISION_LOG.md`.
→ Affects: everyone. Telephony emits timestamped evidence; realtime transcribes; notify
  gates recap delivery; no model or dashboard path may create a commitment directly.

## 2026-08-29T12:19-0500 · repo-wide · Diego/claude
Initial project structure: `backend/` (FastAPI, uv, 10 packages + `domain/` leaf),
`dashboard/` (Vite + React), `supabase/`, and `docs/ARCHITECTURE.md` justifying every
directory. Layering is enforced by `backend/tests/test_layering.py`, not by convention.
→ Affects: everyone. Read `docs/ARCHITECTURE.md` §7 before adding code — it says which
  package your file belongs in. Setup is now `uv sync`, not `pip install -r`; commands
  in `AGENTS.md` are `uv run …`. Adding a directory under `app/` fails the build until
  you declare its imports in `ALLOWED`.

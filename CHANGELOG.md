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

## 2026-08-29T17:23-05 · supabase, domain, agent · Codex
Added `call_recaps.agreement_candidates` as a non-null JSONB array for audio-anchored
agreement evidence. The model writes candidates only; deterministic policy remains the
sole future authority that can write commitments.
→ Affects: dashboard and policy. Read the candidates from the persisted recap; never
  treat them as `COMMITTED` without the policy and written-recap gates.

## 2026-08-29T16:47-05 · voice, telephony, ledger, repo, agent · Codex
The live bidirectional call now opens an evidence case, persists final caller and agent
turns with Twilio audio offsets, and produces persisted recap and call-brief reports when
Twilio closes the call. Report output contains audio-anchored agreement candidates only;
it does not write commitments or send any message.
→ Affects: dashboard and policy. Read `/calls/{call_sid}/transcript`, `/recap`, and
  `/brief`; a later deterministic policy step must validate candidates before commitment.

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

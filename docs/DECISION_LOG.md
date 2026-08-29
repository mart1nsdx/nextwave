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

## D7 — Cascade STT → LLM → TTS, not OpenAI's Realtime API

**Decided:** the voice path is three separable stages — Deepgram recognises, an OpenAI
model reasons via the Agents SDK, Deepgram synthesises — orchestrated by us in `voice/`.
`realtime/` was renamed to `voice/` accordingly; keeping the old name would have
described a vendor we no longer use.

**Beat:** OpenAI's speech-to-speech Realtime API, which `docs/CHALLENGE.md` explicitly
suggests ("its Realtime API is a natural fit").

**Why:** three reasons, in order of weight.

1. **We own the turn.** The trial-by-fire is a judge interrupting mid-sentence. With a
   cascade, barge-in is our code: local VAD fires in ~20 ms, we send Twilio `clear`,
   Deepgram `Clear`, and cancel the model run. With speech-to-speech, interruption
   behaviour is the vendor's, and we cannot tune it at hour 20.
2. **Providers are swappable under time pressure.** STT accuracy on a noisy Mexican
   phone line is the single largest risk to the demo, and it is not knowable in advance.
   `STT_PROVIDER` is a one-line change behind a Protocol. Speech-to-speech is all or
   nothing.
3. **The transcript is a first-class artifact, not a byproduct.** The challenge demands
   commitments linked to audio offsets and a call brief. A cascade produces timestamped
   text as its natural intermediate; speech-to-speech makes us ask for it separately.

**Cost:** more moving parts and more latency than one hop — roughly STT endpoint +
model + TTS first-byte rather than a single round-trip. Mitigated by streaming every
stage and by mu-law 8 kHz end to end, so nothing resamples.

**Would change if:** our own barge-in measures worse on a real line than Realtime's, or
cascade latency lands somewhere a dispatcher reads as dead air. Both are measurable on
a real call, and that measurement is the trigger — not a preference.

# Volta

Voice agent that runs the drayage (port → warehouse trucking) leg of a shipment by phone:
it makes real PSTN calls, negotiates rate and pickup window inside a human-defined
mandate, and turns messy spoken conversation into verified, auditable commitments.

## The one idea

**Speech is probabilistic. Authority is deterministic.**

The model proposes and speaks. A policy engine in plain Python — outside the model, with no
network and no prompt anywhere near it — decides whether a proposal may become a
commitment. The price cap is an `if` statement, not a sentence in a prompt, so *convincing
the model is useless: it never had the authority.*

That split is enforced structurally rather than promised. `tests/test_layering.py` fails the
build if `policy/` ever gains an import that could reach a model or the network, and the
Postgres schema refuses the rest: a trigger rejects any commitment reaching `COMMITTED`
without an audio-anchored evidence row, and a partial unique index makes two open bookings
on one RFQ impossible rather than merely unlikely.

📐 **[Architecture diagrams](docs/ARCHITECTURE.md#4b-the-same-three-ideas-drawn)** — the
trust boundary, the commitment chain, and one call end to end.

## Where each required capability lives

From `docs/CHALLENGE.md` §3. Status is what runs today, not what is planned.

| Required capability | Status | Where |
| --- | --- | --- |
| Real outbound calls over the phone network | ✅ | `telephony/outbound.py` — Twilio REST, real PSTN |
| Quotes and negotiates inside a mandate | ✅ | `policy/engine.py`, `tools/conversation_guard.py` |
| Receives inbound calls and decides in real time | ⚠️ | Answers and negotiates; does not yet write back operation state |
| Commitment written to operation state, verified twice | ✅ | `tools/chain.py` — recap delivered *then* `COMMITTED` |
| Every commitment linked to its audio timestamp | ✅ | `evidence.audio_offset_ms`, recording via `telephony/recording.py` |
| Call brief of actions and mentions | ✅ | `agent/recap.py` |
| Conversation and system stay consistent | ⚠️ | Agent reads context; what it hears does not yet update the operation |
| Ugly cases, escalate mid-call without hanging up | ✅ | `telephony/handoff.py` (Twilio Conference), 19 of 20 `docs/UGLY_CASES.md` rows tested |
| Three carriers in parallel, auditable comparison | ❌ | `policy.select_best` ranks deterministically, but `market/` is empty — today the award runs as `scripts/award_from_recaps.py`, by hand |

Two rows are honestly ⚠️ and one is ❌. `docs/UGLY_CASES.md` names the one row (flat
refusal) with no test, and says why.

## Reading order

- **[`AGENTS.md`](AGENTS.md)** — the eight invariants, and the working rules
- **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)** — why the packages are split this way, with the diagrams
- **[`docs/DECISION_LOG.md`](docs/DECISION_LOG.md)** — decisions, and what each one beat
- **[`docs/UGLY_CASES.md`](docs/UGLY_CASES.md)** — the adversarial table, which *is* the test suite
- **[`docs/EVALUATION.md`](docs/EVALUATION.md)** — how the jury scores this
- **[`docs/VERIFICATION.md`](docs/VERIFICATION.md)** — the call → transcript → recap → email path

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
cd backend
uv sync
cp .env.example .env          # backend/.env.example is the authoritative key list
uv run uvicorn app.main:app --reload --port 8000

cd ../dashboard && npm install && npm run dev
```

`.env` is read from `backend/` or from the repo root, so the command above works either
way. **Recaps need `SENDGRID_API_KEY`, `RECAP_FROM_EMAIL` and `RECAP_TO_EMAIL`**: without
them delivery records as `FAILED` and every commitment stalls at `RECAP_FAILED` — that is
the design, not a bug.

Twilio must reach the local server. `ngrok http 8000`, then
`uv run python -m scripts.point_number` re-points the number at the live tunnel. **The URL
changes on every ngrok restart** and inbound calls 404 in silence until it is re-pointed.

## Checks

```bash
cd backend
uv run pytest                                          # 117 tests, no network, no PSTN
uv run ruff check . && uv run mypy app/
uv run python -m scripts.sim_call --scenario boss_approved   # a hostile call, no cost
```

`sim_call` replays a scripted counterparty through the real turn loop — real barge-in, real
policy — with no phone call and no spend. **Never place a real outbound call from a test:**
it costs money and can dial a real number.

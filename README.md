# Volta

Voice agent that runs the drayage (port → warehouse trucking) leg of a shipment by
phone: it makes real PSTN calls, negotiates rate and pickup window inside a human-defined
mandate, and turns messy spoken conversation into verified, auditable commitments.

- **`AGENTS.md`** — invariants and working rules
- **`docs/ARCHITECTURE.md`** — why the packages are split the way they are
- **`docs/VERIFICATION.md`** — the call → transcript → Supabase → recap → email path
- **`docs/DECISION_LOG.md`** — decisions and their alternatives

## Setup

```bash
cd backend
uv sync
cp .env.example .env
uv run uvicorn app.main:app --reload --port 8000

cd ../dashboard && npm install && npm run dev
```

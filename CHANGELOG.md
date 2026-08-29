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

## 2026-08-29T12:19-0500 · repo-wide · Diego/claude
Initial project structure: `backend/` (FastAPI, uv, 10 packages + `domain/` leaf),
`dashboard/` (Vite + React), `supabase/`, and `docs/ARCHITECTURE.md` justifying every
directory. Layering is enforced by `backend/tests/test_layering.py`, not by convention.
→ Affects: everyone. Read `docs/ARCHITECTURE.md` §7 before adding code — it says which
  package your file belongs in. Setup is now `uv sync`, not `pip install -r`; commands
  in `AGENTS.md` are `uv run …`. Adding a directory under `app/` fails the build until
  you declare its imports in `ALLOWED`.

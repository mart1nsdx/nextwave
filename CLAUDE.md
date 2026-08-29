@AGENTS.md

## Claude Code

`AGENTS.md` above is the single source of truth — keep all shared rules there, not here.
This file exists only because Claude Code reads `CLAUDE.md`, not `AGENTS.md`.

- Use plan mode before changing anything under `backend/app/policy/` or `backend/app/tools/`.
  Those two directories are the authorization boundary; a wrong edit there is invisible until
  a judge exploits it live.
- Run `/context` if instructions seem to be ignored — confirm `CLAUDE.md` is listed under
  Memory files.

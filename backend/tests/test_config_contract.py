"""`.env.example` is the authoritative key list (AGENTS.md), so it has to stay true.

It had drifted: eleven settings were missing from it, and it still documented
`SUPABASE_SERVICE_ROLE_KEY` months after the field was renamed. Nobody noticed because
nothing checked. A teammate copying it got a server that started fine and then failed
mid-call when the recap tried to send.
"""

import pathlib

from app.config import Settings

BACKEND = pathlib.Path(__file__).resolve().parent.parent
EXAMPLE = BACKEND / ".env.example"


def _documented_keys() -> set[str]:
    keys = set()
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            keys.add(line.partition("=")[0].strip())
    return keys


def test_env_example_documents_every_setting() -> None:
    missing = {name.upper() for name in Settings.model_fields} - _documented_keys()
    assert not missing, f"settings with no line in .env.example: {sorted(missing)}"


def test_env_example_documents_nothing_that_is_not_a_setting() -> None:
    """A stale key is worse than a missing one — it looks configured and does nothing."""
    extra = _documented_keys() - {name.upper() for name in Settings.model_fields}
    assert not extra, f".env.example documents keys config.py does not read: {sorted(extra)}"


def test_settings_load_from_the_repo_root_not_the_working_directory() -> None:
    """`cd backend && uvicorn ...` is the documented command; it must find the .env.

    A bare ".env" resolves against the process's working directory, so the file at the
    repo root was invisible and every key read as empty.
    """
    configured = Settings.model_config["env_file"]
    assert configured is not None
    locations = {pathlib.Path(p).resolve() for p in configured}
    assert (BACKEND / ".env").resolve() in locations
    assert (BACKEND.parent / ".env").resolve() in locations

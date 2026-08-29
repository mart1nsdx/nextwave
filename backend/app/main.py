"""FastAPI composition root. The only module allowed to import from anywhere.

Wiring lives here so that every other package stays independently testable.
"""

import logging

import structlog
from fastapi import FastAPI

from app.config import get_settings
from app.telephony.router import router as telephony_router


def configure_logging() -> None:
    """Structured logs, because a call is debugged by filtering on call_id.

    Rendered as key=value rather than JSON: during the build a human reads these in a
    terminal. Never log audio payloads or full transcripts here (AGENTS.md).
    """
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%H:%M:%S"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )


def create_app() -> FastAPI:
    configure_logging()
    application = FastAPI(title="Volta", version="0.1.0")

    if not get_settings().public_base_url:
        # Not fatal — /health and the test suite do not need it — but the single most
        # common way to lose an hour is a stale ngrok URL, so say it at startup rather
        # than letting the first real call fail.
        structlog.get_logger(__name__).warning(
            "public_base_url_unset",
            hint="inbound calls will fail; set PUBLIC_BASE_URL to the current ngrok URL",
        )

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    application.include_router(telephony_router)
    return application


app = create_app()

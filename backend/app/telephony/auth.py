"""Who is allowed to talk to this service.

Two callers reach the HTTP edge and they authenticate in two different ways:

* **Twilio** signs every webhook POST with the account auth token (`X-Twilio-Signature`).
  We recompute that HMAC. Nothing else is required of Twilio and nothing else is trusted.
* **An operator** (the dashboard, a script, a human with curl) presents a shared bearer
  token. `POST /calls` places a real, billable PSTN call to an arbitrary number, so the
  route may not be reachable by whoever finds the tunnel URL.

Both guards fail closed (AGENTS.md invariant #6): an unconfigured secret refuses the
request rather than waving it through. The one deliberate exception is
`validate_twilio_signature=False`, which exists so that `sim_call` and local curl testing
stay usable without an auth token.

MAY IMPORT:  stdlib, fastapi, twilio, app.config.
"""

import secrets
from collections.abc import Awaitable, Callable

import structlog
from fastapi import HTTPException, Request, status
from twilio.request_validator import RequestValidator

from app.config import Settings

log = structlog.get_logger(__name__)

Guard = Callable[[Request], Awaitable[None]]


def signed_url(request: Request, public_base_url: str) -> str:
    """The URL Twilio signed, which is *not* the URL that arrived on the socket.

    ngrok (or any TLS-terminating tunnel) forwards `https://x.ngrok.app/twilio/voice` to
    us as `http://127.0.0.1:8000/twilio/voice`. Twilio's HMAC covers the public URL, so
    validating `request.url` fails every single time behind a tunnel. Rebuild the public
    URL from the configured base and the path we were actually asked for.
    """
    url = f"{public_base_url.rstrip('/')}{request.url.path}"
    return f"{url}?{request.url.query}" if request.url.query else url


def twilio_signature_guard(settings: Settings) -> Guard:
    """FastAPI dependency: reject any webhook Twilio did not sign."""

    async def verify(request: Request) -> None:
        if not settings.validate_twilio_signature:
            return
        if not settings.twilio_auth_token or not settings.public_base_url:
            # Without the token or the public URL there is no way to tell Twilio from
            # anyone else, so the honest answer is that the edge is not ready.
            log.error("twilio_signature_unconfigured", path=request.url.path)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TWILIO_AUTH_TOKEN and PUBLIC_BASE_URL are required to validate webhooks",
            )
        form = await request.form()  # Starlette caches this; the handler re-reads it free.
        params = {key: value for key, value in form.items() if isinstance(value, str)}
        signature = request.headers.get("X-Twilio-Signature", "")
        validator = RequestValidator(settings.twilio_auth_token)
        if not validator.validate(signed_url(request, settings.public_base_url), params, signature):
            log.warning("twilio_signature_rejected", path=request.url.path)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="invalid Twilio signature"
            )

    return verify


def internal_token_guard(settings: Settings) -> Guard:
    """FastAPI dependency: require the shared operator bearer token.

    Interim measure pending the per-actor authorization of D44/D45 — see the decision log
    entry for the shared token. An unset token refuses the route; a hackathon deadline is
    not a reason to leave a dialling endpoint open.
    """

    async def verify(request: Request) -> None:
        expected = settings.internal_api_token
        if not expected:
            log.error("internal_api_token_unset", path=request.url.path)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="INTERNAL_API_TOKEN is unset; this route refuses rather than open",
            )
        scheme, _, presented = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(
            presented.encode("utf-8"), expected.encode("utf-8")
        ):
            log.warning("internal_token_rejected", path=request.url.path)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing or invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return verify

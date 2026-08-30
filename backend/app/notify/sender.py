"""Recap delivery over SendGrid (Twilio Email).

A send failure is returned as ``RecapDelivery(status=FAILED)`` — never raised — so the
caller can record RECAP_FAILED and leave the commitment uncommitted (AGENTS.md #3).
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from app.config import Settings
from app.domain.models import Recap, RecapDelivery, RecapDeliveryStatus
from app.notify.render import bodies, subject

_SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"
_TIMEOUT = httpx.Timeout(15.0)


class NullRecapSender:
    """Used when SendGrid is not configured. Records the intent, sends nothing."""

    async def send(self, recap: Recap, to_email: str) -> RecapDelivery:
        return RecapDelivery(
            call_sid=recap.call_sid,
            status=RecapDeliveryStatus.FAILED,
            to_email=to_email or None,
            error="SENDGRID_API_KEY / RECAP_FROM_EMAIL not configured",
        )


class SendGridRecapSender:
    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.sendgrid_api_key
        self._from_email = settings.recap_from_email
        self._from_name = settings.recap_from_name

    async def send(self, recap: Recap, to_email: str) -> RecapDelivery:
        if not to_email:
            return RecapDelivery(
                call_sid=recap.call_sid,
                status=RecapDeliveryStatus.FAILED,
                error="no recipient email for this call",
            )
        text, html = bodies(recap)
        payload = {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": self._from_email, "name": self._from_name},
            "subject": subject(recap),
            "content": [
                {"type": "text/plain", "value": text},
                {"type": "text/html", "value": html},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                response = await client.post(
                    _SENDGRID_URL,
                    json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
        except httpx.HTTPError as exc:
            return RecapDelivery(
                call_sid=recap.call_sid,
                status=RecapDeliveryStatus.FAILED,
                to_email=to_email,
                error=f"transport error: {exc}",
            )

        if response.status_code == 202:
            return RecapDelivery(
                call_sid=recap.call_sid,
                status=RecapDeliveryStatus.SENT,
                to_email=to_email,
                provider_message_id=response.headers.get("X-Message-Id"),
                sent_at=datetime.now(UTC),
            )
        return RecapDelivery(
            call_sid=recap.call_sid,
            status=RecapDeliveryStatus.FAILED,
            to_email=to_email,
            error=f"sendgrid {response.status_code}: {response.text[:300]}",
        )

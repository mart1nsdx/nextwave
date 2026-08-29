"""Recap email rendering and the SendGrid sender. No real network calls."""

from typing import Any

import httpx
import pytest

from app.config import Settings
from app.domain.models import Recap, RecapDeliveryStatus
from app.notify import NullRecapSender
from app.notify.render import bodies, subject
from app.notify.sender import SendGridRecapSender

RECAP = Recap(
    call_sid="CAmail1",
    summary="El transportista pidio 9,500; el agente se mantuvo en el tope de 9,000.",
    quoted_prices=["9,500 MXN", "9,000 MXN"],
    names=["Juan"],
    objections=["intento subir por encima del tope"],
)


def test_render_includes_summary_and_sections() -> None:
    assert "CAmail1" in subject(RECAP)
    text, html = bodies(RECAP)
    assert "9,500 MXN" in text and "9,000 MXN" in text
    assert "Objeciones" in text
    assert "<li>Juan</li>" in html
    assert "no constituye una reserva confirmada" in text.lower()


async def test_null_sender_reports_not_configured() -> None:
    delivery = await NullRecapSender().send(RECAP, "cliente@example.com")
    assert delivery.status is RecapDeliveryStatus.FAILED
    assert "not configured" in (delivery.error or "")


async def test_sendgrid_missing_recipient_is_failed() -> None:
    sender = SendGridRecapSender(
        Settings(sendgrid_api_key="SG.x", recap_from_email="volta@example.com")
    )
    delivery = await sender.send(RECAP, "")
    assert delivery.status is RecapDeliveryStatus.FAILED
    assert "recipient" in (delivery.error or "")


async def test_sendgrid_success_path(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _FakeClient:
        def __init__(self, *_: Any, **__: Any) -> None: ...

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *_: Any) -> None: ...

        async def post(self, url: str, *, json: Any, headers: Any) -> httpx.Response:
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return httpx.Response(202, headers={"X-Message-Id": "sg_123"})

    monkeypatch.setattr("app.notify.sender.httpx.AsyncClient", _FakeClient)
    sender = SendGridRecapSender(
        Settings(sendgrid_api_key="SG.x", recap_from_email="volta@example.com")
    )

    delivery = await sender.send(RECAP, "dispatch@fletes.mx")

    assert delivery.status is RecapDeliveryStatus.SENT
    assert delivery.provider_message_id == "sg_123"
    assert captured["json"]["personalizations"][0]["to"][0]["email"] == "dispatch@fletes.mx"
    assert captured["headers"]["Authorization"] == "Bearer SG.x"


async def test_sendgrid_error_status_is_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeClient:
        def __init__(self, *_: Any, **__: Any) -> None: ...

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *_: Any) -> None: ...

        async def post(self, *_: Any, **__: Any) -> httpx.Response:
            return httpx.Response(401, text='{"errors":[{"message":"unauthorized"}]}')

    monkeypatch.setattr("app.notify.sender.httpx.AsyncClient", _FakeClient)
    sender = SendGridRecapSender(
        Settings(sendgrid_api_key="SG.bad", recap_from_email="volta@example.com")
    )

    delivery = await sender.send(RECAP, "dispatch@fletes.mx")
    assert delivery.status is RecapDeliveryStatus.FAILED
    assert "401" in (delivery.error or "")

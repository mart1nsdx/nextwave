"""Twilio implementation of the human handoff after policy has authorized it."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog
from twilio.rest import Client

from app.config import Settings
from app.domain.models import HandoffEvent, HandoffRequest, HandoffStatus
from app.domain.ports import TranscriptStore

from .twiml import caller_hold_conference, unavailable_handoff

log = structlog.get_logger(__name__)


class TwilioHandoff:
    """Places the caller on hold, privately briefs the operator, then bridges on consent."""

    def __init__(self, settings: Settings, store: TranscriptStore) -> None:
        self._settings = settings
        self._store = store

    def _client(self) -> Client:
        if not self._settings.twilio_account_sid or not self._settings.twilio_auth_token:
            raise ValueError("Twilio credentials are empty — cannot transfer a call.")
        if not self._settings.twilio_phone_number:
            raise ValueError("TWILIO_PHONE_NUMBER is empty — cannot call the operator.")
        if not self._settings.escalation_phone_number:
            raise ValueError("ESCALATION_PHONE_NUMBER is empty — handoff fails closed.")
        if not self._settings.public_base_url:
            raise ValueError("PUBLIC_BASE_URL is empty — handoff callbacks have no destination.")
        return Client(self._settings.twilio_account_sid, self._settings.twilio_auth_token)

    def _base(self) -> str:
        return self._settings.public_base_url.rstrip("/")

    async def start(self, request: HandoffRequest) -> None:
        client = self._client()
        handoff_id = str(request.handoff_id)
        conference_name = f"volta-handoff-{request.handoff_id.hex}"
        base = self._base()
        await self._store.update_handoff_transport(handoff_id, conference_name=conference_name)
        await self._store.record_handoff_event(
            _event(
                request,
                HandoffStatus.CALLER_ON_HOLD,
                "caller redirected to moderated conference",
            )
        )
        hold_twiml = caller_hold_conference(
            conference_name,
            f"{base}/twilio/handoff/{handoff_id}/wait",
            f"{base}/twilio/handoff/{handoff_id}/conference",
        )
        await asyncio.to_thread(client.calls(request.call_sid).update, twiml=hold_twiml)
        await self._store.record_handoff_event(
            _event(request, HandoffStatus.HUMAN_DIALING, "configured operator dialed")
        )
        try:
            operator_call = await asyncio.to_thread(
                client.calls.create,
                to=self._settings.escalation_phone_number,
                from_=self._settings.twilio_phone_number,
                url=f"{base}/twilio/handoff/{handoff_id}/brief",
                status_callback=f"{base}/twilio/handoff/{handoff_id}/operator-status",
                status_callback_event=["completed"],
            )
        except Exception as exc:
            await self.fail(handoff_id, f"operator dial failed: {type(exc).__name__}")
            return
        await self._store.update_handoff_transport(
            handoff_id, operator_call_sid=str(operator_call.sid)
        )
        log.info("handoff_operator_dialed", call_id=request.call_sid, handoff_id=handoff_id)

    async def fail(self, handoff_id: str, detail: str) -> None:
        request = await self._store.get_handoff(handoff_id)
        if request is None or request.status in {HandoffStatus.CONNECTED, HandoffStatus.COMPLETED}:
            return
        await self._store.record_handoff_event(
            _event(request, HandoffStatus.FAILED, detail, suffix="failed")
        )
        try:
            client = self._client()
            await asyncio.to_thread(
                client.calls(request.call_sid).update, twiml=unavailable_handoff()
            )
        except Exception:
            log.exception("handoff_failure_message_failed", call_id=request.call_sid)


def _event(
    request: HandoffRequest, status: HandoffStatus, detail: str, *, suffix: str | None = None
) -> HandoffEvent:
    event_suffix = suffix or status.value
    return HandoffEvent(
        event_key=f"{request.handoff_id}:{event_suffix}",
        handoff_id=request.handoff_id,
        status=status,
        detail=detail,
        created_at=datetime.now(UTC),
    )

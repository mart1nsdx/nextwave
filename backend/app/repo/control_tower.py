"""Supabase-backed read projections and idempotent control-tower command writes.

The dashboard never receives hard-coded operational fixtures. Its projections come from
the database, where upstream systems and the voice/ledger paths record source-labelled
evidence. Tests inject a repository double instead of changing this production path.
"""

from __future__ import annotations

from typing import Any, Protocol, cast

from supabase import Client, create_client

from app.config import Settings, get_settings
from app.domain import (
    BotConfiguration,
    CallEvidence,
    CallSummary,
    CommandResult,
    EvidencePointer,
    FxSnapshot,
    Mandate,
    OperationConfiguration,
    OperationSummary,
    OperationWorkspace,
    PolicyDecisionSummary,
    TranscriptLine,
    TrustedSessionIdentity,
)

__all__ = [
    "ControlTowerRepository",
    "ControlTowerStorageUnavailable",
    "SupabaseControlTowerRepository",
]


class ControlTowerStorageUnavailable(RuntimeError):
    """Raised when the server cannot safely read its authoritative data source."""


class ControlTowerRepository(Protocol):
    """Persistence seam used by the market layer and replaced only in tests."""

    def list_operations(self) -> list[OperationSummary]: ...

    def get_workspace(self, operation_id: str) -> OperationWorkspace | None: ...

    def get_calls(self, operation_id: str) -> list[CallSummary]: ...

    def list_calls(self) -> list[CallSummary]: ...

    def get_evidence(self, call_id: str) -> CallEvidence | None: ...

    def get_configuration(self, operation_id: str) -> OperationConfiguration | None: ...

    def get_command(self, idempotency_key: str) -> CommandResult | None: ...

    def activate_rfq(
        self, operation_id: str, carrier_ids: list[str], idempotency_key: str
    ) -> CommandResult: ...

    def request_award(
        self, operation_id: str, offer_id: str, idempotency_key: str
    ) -> CommandResult: ...


class SupabaseControlTowerRepository:
    """Authoritative server-side database adapter for dashboard projections.

    The browser has no Supabase credentials. The client is created lazily so a missing
    deployment setting returns a controlled API error rather than breaking app startup.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: Client | None = None

    def list_operations(self) -> list[OperationSummary]:
        response = (
            self._database()
            .table("operations")
            .select(
                "id,reference,client_name,container_number,route,stage,attention,"
                "days_remaining,next_action,source_freshness,source_is_demo"
            )
            .execute()
        )
        operations = [OperationSummary.model_validate(row) for row in _rows(_data(response))]
        priority = {"needs_attention": 0, "working": 1, "executing": 2}
        return sorted(operations, key=lambda item: priority.get(item.attention, 3))

    def get_workspace(self, operation_id: str) -> OperationWorkspace | None:
        response = (
            self._database()
            .table("operation_workspaces")
            .select("workspace")
            .eq("operation_id", operation_id)
            .maybe_single()
            .execute()
        )
        row = _row(_data(response))
        if row is None:
            return None
        return OperationWorkspace.model_validate(row["workspace"])

    def get_calls(self, operation_id: str) -> list[CallSummary]:
        response = (
            self._database()
            .table("call_cases")
            .select(_CALL_COLUMNS)
            .eq("operation_id", operation_id)
            .order("started_at", desc=True)
            .execute()
        )
        return [_call_summary(row) for row in _rows(_data(response))]

    def list_calls(self) -> list[CallSummary]:
        response = (
            self._database()
            .table("call_cases")
            .select(_CALL_COLUMNS)
            .order("started_at", desc=True)
            .execute()
        )
        return [_call_summary(row) for row in _rows(_data(response))]

    def get_evidence(self, call_id: str) -> CallEvidence | None:
        response = (
            self._database()
            .table("call_cases")
            .select(
                f"{_CALL_COLUMNS},call_brief,transcript,policy_decisions,recap_status,"
                "recording_id,audio_offset_ms,transcript_event_id,audio_url,is_demo"
            )
            .eq("id", call_id)
            .maybe_single()
            .execute()
        )
        row = _row(_data(response))
        if row is None:
            return None
        evidence = None
        if row["recording_id"] is not None:
            evidence = EvidencePointer(
                recording_id=row["recording_id"],
                audio_offset_ms=row["audio_offset_ms"],
                transcript_event_id=row["transcript_event_id"],
                audio_url=row["audio_url"],
            )
        return CallEvidence(
            call=_call_summary(row),
            call_brief=[str(item) for item in row["call_brief"]],
            transcript=[TranscriptLine.model_validate(item) for item in row["transcript"]],
            policy_decisions=[
                PolicyDecisionSummary.model_validate(item) for item in row["policy_decisions"]
            ],
            recap_status=row["recap_status"],
            evidence=evidence,
            is_demo=row["is_demo"],
        )

    def get_configuration(self, operation_id: str) -> OperationConfiguration | None:
        client = self._database()
        profile_response = (
            client.table("operation_bot_profiles")
            .select("agent_name,agent_role,primary_language,fallback_language,recap_channel")
            .eq("operation_id", operation_id)
            .maybe_single()
            .execute()
        )
        profile = _row(_data(profile_response))
        mandate_response = (
            client.table("active_mandates")
            .select(
                "mandate_id,version,owner_id,operation_id,max_all_in_usd,pickup_not_before,"
                "pickup_not_after,allowed_equipment,commitment_mode,fx_margin_bps"
            )
            .eq("operation_id", operation_id)
            .maybe_single()
            .execute()
        )
        mandate = _row(_data(mandate_response))
        trusted_session_response = (
            client.table("trusted_sessions")
            .select("trusted_carrier_name,trusted_carrier_id,trusted_contact_id")
            .eq("operation_id", operation_id)
            .maybe_single()
            .execute()
        )
        trusted_session = _row(_data(trusted_session_response))
        if profile is None or mandate is None or trusted_session is None:
            return None
        snapshots_response = (
            client.table("fx_snapshots")
            .select("snapshot_id,quote_currency,usd_per_unit,observed_at,source")
            .eq("operation_id", operation_id)
            .order("observed_at", desc=True)
            .execute()
        )
        snapshots = _rows(_data(snapshots_response))
        return OperationConfiguration(
            operation_id=operation_id,
            bot=BotConfiguration.model_validate(profile),
            mandate=Mandate.model_validate(mandate),
            fx_snapshots=[FxSnapshot.model_validate(snapshot) for snapshot in snapshots],
            trusted_session=TrustedSessionIdentity.model_validate(trusted_session),
            is_demo=False,
        )

    def get_command(self, idempotency_key: str) -> CommandResult | None:
        response = (
            self._database()
            .table("operator_command_results")
            .select("result")
            .eq("idempotency_key", idempotency_key)
            .maybe_single()
            .execute()
        )
        row = _row(_data(response))
        return CommandResult.model_validate(row["result"]) if row else None

    def activate_rfq(
        self, operation_id: str, carrier_ids: list[str], idempotency_key: str
    ) -> CommandResult:
        response = (
            self._database()
            .rpc(
                "control_tower_activate_rfq",
                {
                    "p_operation_id": operation_id,
                    "p_carrier_ids": carrier_ids,
                    "p_idempotency_key": idempotency_key,
                },
            )
            .execute()
        )
        return CommandResult.model_validate(_data(response))

    def request_award(
        self, operation_id: str, offer_id: str, idempotency_key: str
    ) -> CommandResult:
        response = (
            self._database()
            .rpc(
                "control_tower_request_award",
                {
                    "p_operation_id": operation_id,
                    "p_offer_id": offer_id,
                    "p_idempotency_key": idempotency_key,
                },
            )
            .execute()
        )
        return CommandResult.model_validate(_data(response))

    def _database(self) -> Client:
        if not self._settings.supabase_url or not self._settings.supabase_service_role_key:
            raise ControlTowerStorageUnavailable(
                "The control tower database is not configured on this server."
            )
        if self._client is None:
            self._client = create_client(
                self._settings.supabase_url, self._settings.supabase_service_role_key
            )
        return self._client


_CALL_COLUMNS = (
    "id,operation_id,carrier_name,direction,status,started_at,duration_seconds,summary,"
    "has_evidence,is_demo"
)


def _rows(value: object) -> list[dict[str, Any]]:
    """Contain untyped PostgREST results at the repository boundary."""
    return cast(list[dict[str, Any]], value or [])


def _row(value: object) -> dict[str, Any] | None:
    """Contain optional PostgREST results at the repository boundary."""
    return cast(dict[str, Any] | None, value)


def _data(response: object) -> object:
    """Read an SDK response without allowing its broad type to escape the adapter."""
    return getattr(response, "data", None)


def _call_summary(row: dict[str, Any]) -> CallSummary:
    return CallSummary.model_validate({column: row[column] for column in _CALL_COLUMNS.split(",")})

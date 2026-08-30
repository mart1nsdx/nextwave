"""FastAPI composition root. The only module allowed to import from anywhere.

Wiring lives here so that every other package stays independently testable.
"""

import logging

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.domain import (
    ActivationRequest,
    AwardRequest,
    CallEvidence,
    CallSummary,
    CommandResult,
    OperationConfiguration,
    OperationSummary,
    OperationWorkspace,
)
from app.market.control_tower import ControlTowerService
from app.repo import ControlTowerStorageUnavailable, SupabaseControlTowerRepository
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


def create_app(control_tower: ControlTowerService | None = None) -> FastAPI:
    configure_logging()
    application = FastAPI(title="Volta", version="0.1.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
            "http://localhost:5175",
            "http://127.0.0.1:5175",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    dashboard = control_tower or ControlTowerService(SupabaseControlTowerRepository())

    @application.exception_handler(ControlTowerStorageUnavailable)
    def control_tower_storage_unavailable(
        _: Request, error: ControlTowerStorageUnavailable
    ) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(error)})

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

    @application.get("/operations", response_model=list[OperationSummary])
    def list_operations() -> list[OperationSummary]:
        """Return the database-backed operational work queue."""
        return dashboard.list_operations()

    @application.get("/operations/{operation_id}/workspace", response_model=OperationWorkspace)
    def get_operation_workspace(operation_id: str) -> OperationWorkspace:
        workspace = dashboard.get_workspace(operation_id)
        if workspace is None:
            raise HTTPException(status_code=404, detail="operation not found")
        return workspace

    @application.get("/operations/{operation_id}/calls", response_model=list[CallSummary])
    def get_operation_calls(operation_id: str) -> list[CallSummary]:
        if dashboard.get_workspace(operation_id) is None:
            raise HTTPException(status_code=404, detail="operation not found")
        return dashboard.get_calls(operation_id)

    @application.get(
        "/operations/{operation_id}/configuration", response_model=OperationConfiguration
    )
    def get_operation_configuration(operation_id: str) -> OperationConfiguration:
        configuration = dashboard.get_configuration(operation_id)
        if configuration is None:
            raise HTTPException(status_code=404, detail="operation configuration not found")
        return configuration

    @application.get("/calls", response_model=list[CallSummary])
    def list_calls() -> list[CallSummary]:
        return dashboard.list_calls()

    @application.get("/calls/{call_id}/evidence", response_model=CallEvidence)
    def get_call_evidence(call_id: str) -> CallEvidence:
        evidence = dashboard.get_evidence(call_id)
        if evidence is None:
            raise HTTPException(status_code=404, detail="call evidence not found")
        return evidence

    @application.post(
        "/operations/{operation_id}/rfqs/{rfq_id}/activate", response_model=CommandResult
    )
    def activate_rfq(operation_id: str, rfq_id: str, request: ActivationRequest) -> CommandResult:
        try:
            return dashboard.activate_rfq(operation_id, rfq_id, request)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="operation or RFQ not found") from error

    @application.post(
        "/operations/{operation_id}/rfqs/{rfq_id}/request-award",
        response_model=CommandResult,
    )
    def request_award(operation_id: str, rfq_id: str, request: AwardRequest) -> CommandResult:
        try:
            return dashboard.request_award(operation_id, rfq_id, request)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="operation or RFQ not found") from error

    application.include_router(telephony_router)
    return application


app = create_app()

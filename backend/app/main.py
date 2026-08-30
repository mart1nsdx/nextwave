"""FastAPI composition root for the call-evidence and post-call report path."""

import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import structlog
from fastapi import FastAPI, HTTPException

from app.agent import (
    DEMO_PROFILE,
    CallPhase,
    OpenAIRecapModel,
    build_brief,
    build_recap,
    demo_context,
)
from app.config import Settings, get_settings
from app.domain.binding import CallBinding
from app.domain.models import (
    CallBrief,
    CallCase,
    CallDirection,
    HandoffReason,
    Recap,
    RecapContext,
    Speaker,
    TranscriptEvent,
    TranscriptTrack,
)
from app.domain.ports import RecapModel, TranscriptStore
from app.domain.security import CommitmentMode, Mandate
from app.ledger import EvidenceLedger
from app.repo import InMemoryTranscriptStore, SupabaseTranscriptStore
from app.telephony.handoff import TwilioHandoff
from app.telephony.router import create_router
from app.tools import HandoffTool
from app.voice.session import VoiceSession, build_session

log = structlog.get_logger(__name__)


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%H:%M:%S"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )


class RecapService:
    """Generates reports from stored evidence. It never creates a commitment."""

    def __init__(self, ledger: EvidenceLedger, store: TranscriptStore, model: RecapModel) -> None:
        self._ledger = ledger
        self._store = store
        self._model = model

    async def run(self, call_sid: str, *, context: RecapContext | None = None) -> Recap | None:
        transcript = await self._ledger.transcript_text(call_sid)
        if not transcript.strip():
            log.warning("recap_skipped_without_evidence", call_id=call_sid)
            return None
        recap = await build_recap(call_sid, transcript, self._model, context=context)
        brief = await build_brief(call_sid, transcript, self._model)
        await self._store.save_recap(recap)
        await self._store.save_brief(brief)
        return recap


def phase_for(direction: CallDirection) -> CallPhase:
    """Which conversation this is, decided by who dialed whom.

    Never inferred from what is said. A call we placed is an RFQ; a call that reached us
    is from someone we have not identified yet, and the inbound rules exist precisely to
    stop the agent confirming a reference, a rate or a schedule to a stranger. Letting the
    model pick the phase would let the counterparty pick it.

    AWARD and RENEGOTIATION are reached by market/ selecting a carrier, not by direction,
    so they are not produced here yet.
    """
    return CallPhase.INBOUND if direction is CallDirection.INBOUND else CallPhase.RFQ


# --------------------------------------------------------------- the case, mocked

# The one demo operation and the mandate that governs it. This is authority data, not
# wording, which is why it is here and not in agent/demo.py: when a human writes a
# mandate in the dashboard it will arrive through repo/, and this block is what that
# lookup replaces.
#
# The USD ceiling is a separately human-set figure, NOT a conversion of the 9,000 MXN
# negotiating ceiling the agent talks with. Nothing in this codebase converts currency
# without an approved immutable FX snapshot (invariant #9), and inventing a rate to make
# these two numbers line up would be exactly that failure.
DEMO_OPERATION_REF = "OP-1042"

DEMO_MANDATE = Mandate(
    mandate_id="MND-1042",
    version=1,
    owner_id="textiles-pacifico/ops",
    operation_id=DEMO_OPERATION_REF,
    max_all_in_usd=Decimal("500"),
    pickup_not_before=datetime(2026, 9, 2, 6, 0, tzinfo=UTC),
    pickup_not_after=datetime(2026, 9, 4, 23, 59, tzinfo=UTC),
    allowed_equipment=frozenset({"chasis de 40 pies"}),
    # Volta never commits autonomously: a call produces a pre-agreement and a human
    # closes it (invariant #3).
    commitment_mode=CommitmentMode.HUMAN_ESCALATION,
)


def _digits(number: str) -> str:
    """Compare phone numbers by their digits. Twilio's formatting is not ours to trust."""
    return re.sub(r"\D", "", number)


class InMemoryCaseBindings:
    """The case spine, as three dicts. Deliberately trivial and deliberately temporary.

    Two competing pull requests define the real repository and schema for this, and only
    one will survive, so nothing outside this class depends on either. When one merges,
    every method here becomes a query and `CallBinding` stops being constructed by hand;
    the resolver Protocol in domain/ports.py is what keeps that a local change.

    What is *not* temporary is the ordering and the failure mode: a case exists before a
    number is dialled, and a call that cannot be tied to exactly one case resolves to
    None so the caller escalates.
    """

    def __init__(self, store: TranscriptStore) -> None:
        self._store = store
        self._by_case: dict[str, CallBinding] = {}
        self._by_call_sid: dict[str, str] = {}
        # A number can legitimately be attached to more than one case — the same
        # dispatcher, two lanes. That is why this is a set: two candidates is an
        # ambiguity to escalate, not a coin to flip.
        self._cases_by_number: dict[str, set[str]] = {}

    async def reserve(self, to_number: str) -> str:
        """Write the case for a call we are about to place. Returns its case id."""
        case_id = f"case-{uuid4().hex[:12]}"
        self._by_case[case_id] = CallBinding(
            case_id=case_id,
            operation_ref=DEMO_OPERATION_REF,
            direction=CallDirection.OUTBOUND,
            mandate=DEMO_MANDATE,
        )
        self._cases_by_number.setdefault(_digits(to_number), set()).add(case_id)
        log.info("case_reserved", case_id=case_id, operation_ref=DEMO_OPERATION_REF)
        return case_id

    async def bind(self, case_id: str, call_sid: str) -> None:
        """Attach Twilio's CallSid to a case that was already written."""
        binding = self._by_case.get(case_id)
        if binding is None:
            log.error("bind_unknown_case", case_id=case_id, call_id=call_sid)
            return
        self._by_case[case_id] = binding.with_call_sid(call_sid)
        self._by_call_sid[call_sid] = case_id

    async def resolve(self, call_sid: str, custom: Mapping[str, str]) -> CallBinding | None:
        """The case this call is about, or None — which means escalate, never guess.

        Stops at the first unambiguous hit:

        1. a case id we already tied to this CallSid — the post-call and redelivery path;
        2. the `case_id` custom parameter Twilio echoes back from the <Stream> we built,
           which is how every call we placed identifies itself with no lookup at all;
        3. the caller's number resolving to exactly one live case — the inbound path.

        A fourth rule belongs here, from docs: a spoken container number resolving to
        exactly one operation. It is not implemented because it cannot be: it needs both
        a live turn of conversation and the operation index the contested spine defines.
        Its absence is safe in the only way that matters — an inbound caller we cannot
        place falls through to None and gets a person.
        """
        bound = self._by_call_sid.get(call_sid)
        if bound is not None:
            return self._by_case.get(bound)

        case_id = custom.get("case_id")
        if case_id:
            binding = self._by_case.get(case_id)
            if binding is None:
                # The stream named a case we do not have. That is a bug or a forged
                # parameter; either way it is not a reason to pick something else.
                log.error("case_id_unknown", call_id=call_sid, case_id=case_id)
                return None
            bound_binding = binding.with_call_sid(call_sid)
            self._by_case[case_id] = bound_binding
            self._by_call_sid[call_sid] = case_id
            return bound_binding

        case = await self._store.get_case(call_sid)
        if case is None or not case.from_number:
            return None
        candidates = self._cases_by_number.get(_digits(case.from_number), set())
        if len(candidates) != 1:
            log.warning("inbound_number_ambiguous", call_id=call_sid, candidates=len(candidates))
            return None
        binding = self._by_case[next(iter(candidates))]
        inbound = binding.model_copy(
            update={"call_sid": call_sid, "direction": CallDirection.INBOUND}
        )
        self._by_call_sid[call_sid] = inbound.case_id
        return inbound


def mandate_summary(mandate: Mandate) -> str:
    """One line of reference for the recap model. It never decides anything."""
    return (
        f"{mandate.mandate_id} v{mandate.version}: all-in ceiling "
        f"{mandate.max_all_in_usd} USD, {mandate.commitment_mode.value}"
    )


def _build_store(settings: Settings) -> TranscriptStore:
    if settings.supabase_url and settings.supabase_secret_key:
        return SupabaseTranscriptStore(settings)
    log.warning("supabase_unconfigured_using_memory_store")
    return InMemoryTranscriptStore()


def create_app(
    settings: Settings | None = None,
    store: TranscriptStore | None = None,
    recap_model: RecapModel | None = None,
) -> FastAPI:
    configure_logging()
    settings = settings or get_settings()
    store = store or _build_store(settings)
    ledger = EvidenceLedger(store)
    recap_model = recap_model or OpenAIRecapModel(
        settings.openai_api_key,
        settings.openai_recap_model or settings.openai_agent_model,
    )
    recap_service = RecapService(ledger, store, recap_model)
    twilio_handoff = TwilioHandoff(settings, store)
    handoff_tool = HandoffTool(store, twilio_handoff.start)
    case_bindings = InMemoryCaseBindings(store)
    sequence_by_call: dict[str, int] = {}

    async def persist_final(
        call_sid: str,
        track: TranscriptTrack,
        speaker: Speaker,
        offset_ms: int,
        text: str,
    ) -> None:
        if not call_sid:
            log.error("transcript_without_call_id")
            return
        if call_sid not in sequence_by_call:
            sequence_by_call[call_sid] = len(await ledger.transcript(call_sid))
        sequence_by_call[call_sid] += 1
        await ledger.record_segment(
            call_sid,
            track=track,
            sequence_number=sequence_by_call[call_sid],
            audio_offset_ms=offset_ms,
            text=text,
            is_final=True,
            speaker=speaker,
        )

    async def recap_context(call_sid: str) -> RecapContext | None:
        """What the recap is allowed to know beyond the transcript: which case it was.

        Without this the summary of every call is written against a blank context, so a
        report of a negotiation cannot say which operation it belongs to or which
        authorization it ran under. The mandate goes in for reference in the prose only;
        the model never decides whether it was respected (RecapContext's own docstring).
        """
        binding = await case_bindings.resolve(call_sid, {})
        if binding is None:
            log.warning("recap_without_case", call_id=call_sid)
            return None
        return RecapContext(
            operation_ref=binding.operation_ref,
            mandate_summary=mandate_summary(binding.mandate),
        )

    async def complete_call(call_sid: str) -> None:
        try:
            await recap_service.run(call_sid, context=await recap_context(call_sid))
        except Exception:
            # A report failure must be visible and must never manufacture a commitment.
            log.exception("recap_generation_failed", call_id=call_sid)

    async def request_handoff(
        call_sid: str, reason: HandoffReason, offset_ms: int, note: str
    ) -> bool:
        return await handoff_tool.propose_handoff(call_sid, reason, offset_ms, note) is not None

    def make_session(binding: CallBinding) -> VoiceSession:
        """Compose one call's prompt, here, where the business data enters the system.

        The operation reference comes from the binding, not from the mock: two calls on
        two cases now produce two different prompts, which is the whole point of the
        resolution step above. DEMO_PROFILE and the rest of demo_context() are still
        mocked (agent/demo.py) — that is the seam a real profile arrives through.

        The mandate travels on the session rather than into the prompt's spoken ceiling.
        Those are two different quantities: the mandate's ceiling is all-in USD because
        policy is always USD, and the figure the agent negotiates with is in the
        operation's own currency. Joining them needs the FX snapshot invariant #9
        requires, which is not ours to invent here.
        """
        context = demo_context(phase_for(binding.direction)).model_copy(
            update={"reference": binding.operation_ref}
        )
        return build_session(
            settings,
            DEMO_PROFILE,
            context,
            binding,
            on_final_transcript=persist_final,
            on_handoff=request_handoff,
        )

    application = FastAPI(title="Volta", version="0.1.0")
    application.state.recap_service = recap_service
    application.state.case_bindings = case_bindings
    application.include_router(
        create_router(
            settings,
            store,
            complete_call,
            persist_final,
            twilio_handoff,
            request_handoff,
            make_session,
            case_bindings.resolve,
            case_bindings,
        )
    )

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/calls")
    async def list_calls(limit: int = 50) -> list[CallCase]:
        return await store.list_cases(limit=limit)

    @application.get("/calls/{call_sid}/transcript")
    async def get_transcript(call_sid: str) -> list[TranscriptEvent]:
        events = await store.list_events(call_sid)
        if not events and await store.get_case(call_sid) is None:
            raise HTTPException(status_code=404, detail="call not found")
        return events

    @application.get("/calls/{call_sid}/recap")
    async def get_recap(call_sid: str) -> Recap:
        recap = await store.get_recap(call_sid)
        if recap is None:
            raise HTTPException(status_code=404, detail="recap not generated")
        return recap

    @application.get("/calls/{call_sid}/brief")
    async def get_brief(call_sid: str) -> CallBrief:
        brief = await store.get_brief(call_sid)
        if brief is None:
            raise HTTPException(status_code=404, detail="brief not generated")
        return brief

    @application.post("/calls/{call_sid}/recap")
    async def regenerate_recap(call_sid: str) -> Recap:
        if await store.get_case(call_sid) is None:
            raise HTTPException(status_code=404, detail="call not found")
        recap = await recap_service.run(call_sid, context=await recap_context(call_sid))
        if recap is None:
            raise HTTPException(status_code=409, detail="no transcript to summarize")
        return recap

    return application


app = create_app()

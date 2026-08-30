"""Shared types. The only leaf package: Operation, Quote, Commitment, Mandate, events.

MAY IMPORT:  stdlib, pydantic. Nothing from app.
IMPORTED BY: everyone.

Types only — no behaviour, no I/O, no decisions. If a function here would need to know
whether something is *allowed*, it belongs in policy/ instead.
"""

from app.domain.binding import CallBinding
from app.domain.company import BusinessType, CompanyProfile
from app.domain.models import (
    BriefAction,
    BriefMention,
    CallBrief,
    CallCase,
    CallDirection,
    CallStatus,
    Recap,
    RecapContext,
    RecapDelivery,
    RecapDeliveryStatus,
    Speaker,
    TranscriptEvent,
    TranscriptTrack,
    build_event_key,
)
from app.domain.ports import (
    CallCompletedHook,
    CaseResolver,
    OutboundCases,
    RecapModel,
    RecapSender,
    TranscriptSink,
    TranscriptStore,
)
from app.domain.security import CommitmentMode, Mandate

__all__ = [
    "BriefAction",
    "BriefMention",
    "BusinessType",
    "CallBinding",
    "CallBrief",
    "CallCase",
    "CallCompletedHook",
    "CallDirection",
    "CallStatus",
    "CaseResolver",
    "CommitmentMode",
    "CompanyProfile",
    "Mandate",
    "OutboundCases",
    "Recap",
    "RecapContext",
    "RecapDelivery",
    "RecapDeliveryStatus",
    "RecapModel",
    "RecapSender",
    "Speaker",
    "TranscriptEvent",
    "TranscriptSink",
    "TranscriptStore",
    "TranscriptTrack",
    "build_event_key",
]

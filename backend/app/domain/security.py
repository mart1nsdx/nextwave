"""Immutable values crossing Volta's untrusted/trusted security boundary."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CommitmentMode(StrEnum):
    AUTONOMOUS = "autonomous"
    HUMAN_ESCALATION = "human_escalation"


class Mandate(BaseModel):
    model_config = ConfigDict(frozen=True)

    mandate_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    owner_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    max_all_in_usd: Decimal = Field(gt=0)
    pickup_not_before: datetime
    pickup_not_after: datetime
    allowed_equipment: frozenset[str] = Field(min_length=1)
    commitment_mode: CommitmentMode
    fx_margin_bps: int | None = Field(default=None, ge=0)

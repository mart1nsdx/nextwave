"""Authoritative immutable security-kernel types.

These are the only customer-configurable authorization inputs the policy layer accepts.
They are deliberately separate from runtime call evidence: neither caller speech, model
output, recaps, nor tools can mutate a mandate.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "CommitmentMode",
    "CostComponent",
    "FxSnapshot",
    "Mandate",
    "QuoteProposal",
    "TrustedSessionIdentity",
]


class CommitmentMode(StrEnum):
    AUTONOMOUS = "autonomous"
    HUMAN_ESCALATION = "human_escalation"


def _require_timezone(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


class Mandate(BaseModel):
    """Immutable human authorization for exactly one operation."""

    model_config = ConfigDict(frozen=True)

    mandate_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    owner_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    max_all_in_usd: Decimal = Field(gt=Decimal("0"))
    pickup_not_before: datetime
    pickup_not_after: datetime
    allowed_equipment: frozenset[str] = Field(min_length=1)
    commitment_mode: CommitmentMode
    fx_margin_bps: int | None = Field(default=None, ge=0)

    @field_validator("pickup_not_before", "pickup_not_after")
    @classmethod
    def pickup_time_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _require_timezone(value)

    @field_validator("allowed_equipment")
    @classmethod
    def equipment_must_not_contain_empty_values(cls, value: frozenset[str]) -> frozenset[str]:
        if any(not equipment.strip() for equipment in value):
            raise ValueError("allowed_equipment cannot contain an empty value")
        return value

    def model_post_init(self, __context: object) -> None:
        if self.pickup_not_after < self.pickup_not_before:
            raise ValueError("pickup_not_after must be on or after pickup_not_before")


class FxSnapshot(BaseModel):
    """Immutable external-rate evidence; freshness is evaluated by policy with an injected clock."""

    model_config = ConfigDict(frozen=True)

    snapshot_id: str = Field(min_length=1)
    quote_currency: str = Field(pattern=r"^[A-Z]{3}$")
    usd_per_unit: Decimal = Field(gt=Decimal("0"))
    observed_at: datetime
    source: str = Field(min_length=1)

    @field_validator("observed_at")
    @classmethod
    def observed_time_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _require_timezone(value)


class TrustedSessionIdentity(BaseModel):
    """Identity obtained from a directory or authenticated session, never from caller speech."""

    model_config = ConfigDict(frozen=True)

    trusted_carrier_name: str = Field(min_length=1)
    trusted_carrier_id: str = Field(min_length=1)
    trusted_contact_id: str = Field(min_length=1)


class CostComponent(BaseModel):
    """One payable part of a proposal; all components must be visible to policy."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    amount: Decimal = Field(ge=Decimal("0"))
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class QuoteProposal(BaseModel):
    """Runtime call evidence. This is not a customer-configurable authorization."""

    model_config = ConfigDict(frozen=True)

    proposal_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    carrier_id: str = Field(min_length=1)
    carrier_contact_id: str = Field(min_length=1)
    components: tuple[CostComponent, ...] = Field(min_length=1)
    cost_is_final: bool
    pickup_at: datetime
    equipment: str = Field(min_length=1)
    valid_until: datetime
    source_call_id: str = Field(min_length=1)
    source_event_id: str = Field(min_length=1)
    transcript_anchor_ms: int = Field(ge=0)
    carrier_confirmed_exact_recap: bool
    confirmed_at: datetime

    @field_validator("pickup_at", "valid_until", "confirmed_at")
    @classmethod
    def proposal_time_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _require_timezone(value)

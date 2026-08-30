"""Deterministic grammar-bound mediation around the untrusted language model."""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from app.domain import (
    CommitmentMode,
    CostComponent,
    FxSnapshot,
    Mandate,
    PolicyOutcome,
    QuoteProposal,
    ReasonCode,
)
from app.policy import evaluate_quote

ESCALATION_RESPONSE = (
    "That exceeds my authority. I cannot accept or commit; I will escalate it to my team."
)
NON_BINDING_RESPONSE = "I can record that only as a non-binding pre-agreement for policy review."
AMBIGUOUS_AMOUNT_RESPONSE = "Please repeat the exact amount in digits and include the currency."
MISSING_FINAL_RESPONSE = "Is that the final all-in cost, including every payable charge?"
MISSING_PICKUP_RESPONSE = "What is the exact pickup date, including month, day, and year?"
MISSING_EQUIPMENT_RESPONSE = "What exact equipment is included in that quote?"
MISSING_VALIDITY_RESPONSE = "Until what exact date is the quote valid?"
FX_MISSING_RESPONSE = (
    "I cannot evaluate that currency without approved exchange-rate evidence, "
    "so I will escalate it."
)
IDENTITY_RESPONSE = (
    "I cannot change the verified caller identity; my team must verify your identity."
)

_DIGIT_AMOUNT = r"\d[\d,]*(?:\.\d{1,2})?"
_NUMBER_WORD = (
    r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
    r"fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|"
    r"sixty|seventy|eighty|ninety|hundred|thousand|million|and|[- ])+"
)
_CURRENCY_TEXT = (
    r"USD|MXN|EUR|CAD|GBP|US dollars?|Mexican pesos?|euros?|"
    r"Canadian dollars?|British pounds?"
)
_MONEY = re.compile(
    rf"(?i)(?:\$\s*(?P<dollar>{_DIGIT_AMOUNT})|"
    rf"(?P<digits>{_DIGIT_AMOUNT})\s*(?P<digit_currency>{_CURRENCY_TEXT})|"
    rf"(?P<words>{_NUMBER_WORD})\s+(?P<word_currency>{_CURRENCY_TEXT}))"
)
_AMBIGUOUS_SHORT_WORDS = re.compile(
    r"(?i)\b(?:rate|price|cost|linehaul|fuel|tolls?|insurance|waiting|detention)\b"
    r"[^.]{0,30}\b(?:one|two|three|four|five|six|seven|eight|nine)(?:[- ]"
    r"(?:one|two|three|four|five|six|seven|eight|nine)){1,3}\b"
)
_AMBIGUOUS_CURRENCY = re.compile(
    rf"(?i)(?:\$?{_DIGIT_AMOUNT}|{_NUMBER_WORD})\s+(?:dollars?|pesos?|pounds?)\b"
)
_MONEY_WITHOUT_CURRENCY = re.compile(
    rf"(?i)\b(?:rate|price|cost|linehaul|fuel|tolls?|insurance|waiting|detention)\b"
    rf"[^.;]{{0,25}}\b(?:{_DIGIT_AMOUNT}|{_NUMBER_WORD})\b"
)
_FINAL_COST = re.compile(r"(?i)\b(?:all[- ]?in|all inclusive|final (?:cost|price|total))\b")
_COMPONENT = re.compile(
    r"(?i)\b(?P<name>linehaul|fuel(?: surcharge)?|tolls?|insurance|waiting|detention|"
    r"overweight|chassis(?: fee)?|terminal(?: fee)?)\b[^.;]{0,28}?"
    rf"(?P<money>\$\s*{_DIGIT_AMOUNT}|{_DIGIT_AMOUNT}\s*(?:USD|MXN|EUR|CAD|GBP|"
    rf"US dollars?|Mexican pesos?|euros?|Canadian dollars?|British pounds?)|"
    rf"{_NUMBER_WORD}\s+(?:USD|MXN|EUR|CAD|GBP|US dollars?|Mexican pesos?|euros?|"
    rf"Canadian dollars?|British pounds?))"
)
_MONTH = r"January|February|March|April|May|June|July|August|September|October|November|December"
_PICKUP_DATE = re.compile(
    rf"(?i)\bpickup(?: is| on| date(?: is)?)?\s+(?P<month>{_MONTH})\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<year>\d{4})\b"
)
_VALID_UNTIL = re.compile(
    rf"(?i)\bvalid until\s+(?P<month>{_MONTH})\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<year>\d{4})\b"
)
_VALID_FOR = re.compile(r"(?i)\bvalid for\s+(?P<count>\d{1,3})\s+(?P<unit>hours?|days?)\b")
_EQUIPMENT_ALIASES: dict[str, str] = {
    "40-foot container chassis": "40-foot container chassis",
    "40 foot container chassis": "40-foot container chassis",
    "forty-foot container chassis": "40-foot container chassis",
    "forty foot container chassis": "40-foot container chassis",
    "dry van": "dry-van",
    "reefer": "reefer",
    "flatbed": "flatbed",
}
_IDENTITY_CLAIM = re.compile(
    r"(?i)\b(?:i am calling from|i'm calling from|calling from|we are from|we're from)\s+"
    r"(?P<identity>[A-Za-z][A-Za-z .&'-]{2,50}?)(?:\s+now)?(?:[,.]|;|$)"
)
_AUTHORITY_CLAIM = re.compile(
    r"(?i)"
    r"\b(?:i|we)\s+(?:accept|agree|confirm|commit|book|award|approve)\b|"
    r"\b(?:it is|it's|that is|that's|this is)\s+(?:booked|confirmed|agreed|accepted|a deal)\b|"
    r"\bwe have a deal\b|\block (?:it|that|this) in\b|\bconsider (?:it|this|that) booked\b|"
    r"\byou have the load\b|\b(?:i'll|i will|we'll|we will) award\b|"
    r"\b(?:let's|let us) (?:move forward|proceed|go ahead)\b|\bthe truck is yours\b|"
    r"\b(?:deal|booking|award) (?:is )?(?:done|final|confirmed)\b"
)

_SMALL = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_CURRENCIES = {
    "usd": "USD",
    "us dollar": "USD",
    "us dollars": "USD",
    "mxn": "MXN",
    "mexican peso": "MXN",
    "mexican pesos": "MXN",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "cad": "CAD",
    "canadian dollar": "CAD",
    "canadian dollars": "CAD",
    "gbp": "GBP",
    "british pound": "GBP",
    "british pounds": "GBP",
}


@dataclass
class _Draft:
    components: dict[str, CostComponent] = field(default_factory=dict)
    cost_is_final: bool = False
    pickup_at: datetime | None = None
    equipment: str | None = None
    valid_until: datetime | None = None
    source_event_id: str = ""
    transcript_anchor_ms: int = 0


def _spoken_integer(value: str) -> Decimal | None:
    tokens = value.lower().replace("-", " ").split()
    if not tokens or all(token == "and" for token in tokens):
        return None
    total = 0
    group = 0
    for token in tokens:
        if token == "and":
            continue
        if token in _SMALL:
            group += _SMALL[token]
        elif token == "hundred" and group:
            group *= 100
        elif token == "thousand" and group:
            total += group * 1_000
            group = 0
        elif token == "million" and group:
            total += group * 1_000_000
            group = 0
        else:
            return None
    return Decimal(total + group)


def _money(match: re.Match[str]) -> tuple[Decimal, str] | None:
    raw = match.group("dollar") or match.group("digits")
    amount: Decimal | None
    if raw is not None:
        try:
            amount = Decimal(raw.replace(",", ""))
        except InvalidOperation:
            return None
    else:
        amount = _spoken_integer(match.group("words") or "")
        if amount is None:
            return None
    currency_text = match.group("digit_currency") or match.group("word_currency")
    currency = "USD" if match.group("dollar") else _CURRENCIES.get(currency_text.lower())
    return (amount, currency) if currency is not None else None


def _date(match: re.Match[str]) -> datetime | None:
    try:
        return datetime.strptime(
            f"{match.group('month')} {match.group('day')} {match.group('year')}", "%B %d %Y"
        ).replace(tzinfo=UTC)
    except ValueError:
        return None


class ConversationGuard:
    """Stateful proposal builder; it can deny or clarify, never commit."""

    def __init__(
        self,
        mandate: Mandate,
        *,
        fx: Mapping[str, FxSnapshot] | None = None,
        now: Callable[[], datetime] | None = None,
        trusted_carrier_name: str = "Pacific Transport",
        trusted_carrier_id: str = "carrier-demo",
        trusted_contact_id: str = "verified-demo-contact",
    ) -> None:
        self._mandate = mandate
        self._fx = dict(fx or {})
        self._now = now or (lambda: datetime.now(UTC))
        self._trusted_carrier_name = trusted_carrier_name.casefold()
        self._trusted_carrier_id = trusted_carrier_id
        self._trusted_contact_id = trusted_contact_id
        self._drafts: dict[str, _Draft] = {}

    def input_directive(self, text: str, *, call_id: str, offset_ms: int) -> str | None:
        """Extract explicit fields, ask for missing facts, and policy-check complete drafts."""
        identity = _IDENTITY_CLAIM.search(text)
        if identity is not None:
            stated = identity.group("identity").strip().casefold()
            if stated != self._trusted_carrier_name:
                return IDENTITY_RESPONSE

        if _AMBIGUOUS_SHORT_WORDS.search(text) or _AMBIGUOUS_CURRENCY.search(text):
            return AMBIGUOUS_AMOUNT_RESPONSE

        draft = self._drafts.setdefault(call_id, _Draft())
        quote_signal = False
        component_spans: set[tuple[int, int]] = set()
        for component_match in _COMPONENT.finditer(text):
            money_match = _MONEY.search(component_match.group("money"))
            parsed = _money(money_match) if money_match is not None else None
            if parsed is None:
                return AMBIGUOUS_AMOUNT_RESPONSE
            amount, currency = parsed
            name = component_match.group("name").lower().replace(" surcharge", "")
            component = CostComponent(name=name, amount=amount, currency=currency)
            previous = draft.components.get(name)
            if previous is not None and previous != component:
                return ESCALATION_RESPONSE
            draft.components[name] = component
            component_spans.add(component_match.span("money"))
            quote_signal = True

        for money_match in _MONEY.finditer(text):
            if any(
                start <= money_match.start() and money_match.end() <= end
                for start, end in component_spans
            ):
                continue
            parsed = _money(money_match)
            if parsed is None:
                return AMBIGUOUS_AMOUNT_RESPONSE
            amount, currency = parsed
            draft.components = {
                "all-in": CostComponent(name="all-in", amount=amount, currency=currency)
            }
            quote_signal = True

        if _FINAL_COST.search(text):
            draft.cost_is_final = True
            quote_signal = True

        pickup_match = _PICKUP_DATE.search(text)
        if pickup_match is not None:
            draft.pickup_at = _date(pickup_match)
            quote_signal = True

        validity_match = _VALID_UNTIL.search(text)
        if validity_match is not None:
            draft.valid_until = _date(validity_match)
            quote_signal = True
        else:
            relative = _VALID_FOR.search(text)
            if relative is not None:
                count = int(relative.group("count"))
                unit = relative.group("unit").lower()
                draft.valid_until = self._now() + (
                    timedelta(hours=count) if unit.startswith("hour") else timedelta(days=count)
                )
                quote_signal = True

        lowered = text.casefold()
        for alias, canonical in _EQUIPMENT_ALIASES.items():
            if alias in lowered:
                draft.equipment = canonical
                quote_signal = True
                break

        if not quote_signal:
            if _MONEY_WITHOUT_CURRENCY.search(text):
                return AMBIGUOUS_AMOUNT_RESPONSE
            return None
        draft.source_event_id = f"heard:{call_id}:{offset_ms}"
        draft.transcript_anchor_ms = offset_ms

        explicit_usd = sum(
            component.amount
            for component in draft.components.values()
            if component.currency == "USD"
        )
        if explicit_usd > self._mandate.max_all_in_usd:
            return ESCALATION_RESPONSE

        if not draft.components:
            return AMBIGUOUS_AMOUNT_RESPONSE
        if not draft.cost_is_final:
            return MISSING_FINAL_RESPONSE
        if draft.pickup_at is None:
            return MISSING_PICKUP_RESPONSE
        if draft.equipment is None:
            return MISSING_EQUIPMENT_RESPONSE
        if draft.valid_until is None:
            return MISSING_VALIDITY_RESPONSE

        now = self._now()
        proposal = QuoteProposal(
            proposal_id=f"spoken:{call_id}:{draft.source_event_id}",
            operation_id=self._mandate.operation_id,
            carrier_id=self._trusted_carrier_id,
            carrier_contact_id=self._trusted_contact_id,
            components=tuple(draft.components.values()),
            cost_is_final=True,
            pickup_at=draft.pickup_at,
            equipment=draft.equipment,
            valid_until=draft.valid_until,
            source_call_id=call_id,
            source_event_id=draft.source_event_id,
            transcript_anchor_ms=draft.transcript_anchor_ms,
        )
        decision = evaluate_quote(self._mandate, proposal, self._fx, now=now)
        if decision.reason is ReasonCode.FX_EVIDENCE_MISSING:
            return FX_MISSING_RESPONSE
        if decision.outcome is not PolicyOutcome.ALLOW:
            return ESCALATION_RESPONSE
        self._drafts.pop(call_id, None)
        return NON_BINDING_RESPONSE

    def filter_model_chunk(self, text: str) -> tuple[str, bool]:
        """Block broad spoken claims of binding authority."""
        if _AUTHORITY_CLAIM.search(text):
            return NON_BINDING_RESPONSE, True
        return text, False


def build_demo_guard(
    *,
    fx: Mapping[str, FxSnapshot] | None = None,
    now: Callable[[], datetime] | None = None,
) -> ConversationGuard:
    return ConversationGuard(
        Mandate(
            mandate_id="DEMO-MANDATE",
            version=1,
            owner_id="demo-owner",
            operation_id="OP-1042",
            max_all_in_usd=Decimal("9000"),
            pickup_not_before=datetime(2026, 9, 2, tzinfo=UTC),
            pickup_not_after=datetime(2026, 9, 4, 23, 59, tzinfo=UTC),
            allowed_equipment=frozenset({"40-foot container chassis"}),
            commitment_mode=CommitmentMode.HUMAN_ESCALATION,
            fx_margin_bps=500,
        ),
        fx=fx,
        now=now,
    )

"""Post-processing award: compare the call recaps of one RFQ and pick a carrier.

    cd backend
    uv run python -m scripts.award_from_recaps --operation-ref OP-MZO-0001
    uv run python -m scripts.award_from_recaps --operation-ref OP-MZO-0001 --commit
    uv run python -m scripts.award_from_recaps --operation-ref OP-MZO-0001 --commit --sms

This is deliberately NOT the live call path. Nothing here decides anything during a
call. It runs afterwards, once every carrier has been phoned and every call has a
`call_recaps` row, and it does one thing:

    take ONE container / RFQ  ->  keep only the carrier calls tied to it (no mixing
                                  cases; a call from another container is excluded)
                              ->  normalise each quote (LLM extraction, never inference)
                              ->  score the carriers with an explainable formula
                              ->  pick the best one
                              ->  draft the confirmation email to that carrier's contact
                              ->  (with --commit) write the offer / participant / commitment rows
                              ->  (with --commit --sms) text the negotiation specs to the
                                  awarded carrier ONLY — nobody else is notified

A call is tied to the RFQ by `call_cases.metadata->>'rfq_id'`, by an existing `offers`
row, or by `--assign CALL_SID=COUNTERPARTY_ID` (which --commit then saves to
`call_cases.metadata` so it stays tied).

The commitment it writes lands at `chain_state = 'VERBAL'`. Reaching `COMMITTED` still
needs the real chain — a confirmed read-back, a sent recap, an `evidence` row — which a
DB trigger enforces and this script never fakes (AGENTS.md invariants #1, #3, #8).

Reads OPENAI_API_KEY / OPENAI_AGENT_MODEL / SUPABASE_URL / SUPABASE_SECRET_KEY from
backend/.env. Dry-run unless --commit is passed.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.config import get_settings

# --- scoring weights ---------------------------------------------------------------
# All positive, summed to 1.0. Change these to change what "best carrier" means.
W_PRICE = 0.45  # lower normalised USD price is better
W_WINDOW = 0.20  # pickup window sits inside the mandate window
W_OBJECTIONS = 0.15  # fewer objections raised on the call
W_FINAL = 0.12  # the carrier gave a final total, not a "más o menos"
W_CLARITY = 0.08  # the negotiation was clear (few re-asks, no ambiguity)
INCOMPLETE_PENALTY = 0.60  # subtracted when the recap has no confirmed price+currency


# --- LLM extraction shape ---------------------------------------------------------
class ExtractedQuote(BaseModel):
    """What one recap explicitly contains. Absent = null, never guessed."""

    price_amount: float | None = Field(
        default=None,
        description="The numeric quote exactly as stated. null if not stated or ambiguous.",
    )
    price_currency: str | None = Field(
        default=None,
        description="ISO 4217 code (MXN, USD, COP). null if the currency was never made explicit.",
    )
    price_is_total_final: bool = Field(
        default=False,
        description="true only if the carrier gave a firm total, not an approximation or a range.",
    )
    pickup_window_start: str | None = Field(
        default=None,
        description="ISO 8601 datetime if an explicit pickup date/time was agreed, else null.",
    )
    pickup_window_end: str | None = Field(default=None, description="ISO 8601 datetime, else null.")
    conditions: list[str] = Field(
        default_factory=list, description="Conditions the carrier attached."
    )
    objections: list[str] = Field(
        default_factory=list, description="Objections or pushback on the call."
    )
    clarity_0_1: float = Field(
        default=0.5,
        description="0..1: 1 = crisp negotiation, 0 = the agent had to re-ask repeatedly.",
    )
    notes: str = Field(default="", description="One line on the negotiation posture.")


EXTRACT_SYSTEM = (
    "You read the recap of one phone call with a freight carrier and extract only what "
    "the transcript makes EXPLICIT. Never infer a number, a currency, or a date. "
    "'ocho cinco' is ambiguous -> price_amount null. '8.5' with no unit -> null. "
    "'el jueves' with no date -> pickup_window null. If the agent asked twice to confirm "
    "the figure and never got a clear answer, price_amount is null and clarity_0_1 is low. "
    "Return strict JSON for the given schema."
)


@dataclass
class Carrier:
    counterparty_id: str
    name: str
    call_sid: str
    case_id: str
    from_number: str | None
    contact_id: str | None
    contact_name: str | None
    contact_phone: str | None
    recap: dict[str, Any]
    tag_source: str = ""  # how this call was tied to the RFQ: metadata | offer | assign
    quote: ExtractedQuote | None = None
    usd_minor: int | None = None
    fx_snapshot_id: str | None = None
    complete: bool = False
    within_mandate: bool | None = None
    score: float = 0.0
    score_breakdown: dict[str, float] = field(default_factory=dict)


# --- Supabase helpers ------------------------------------------------------------
def _db() -> Any:
    s = get_settings()
    if not s.supabase_url or not s.supabase_secret_key:
        sys.exit("SUPABASE_URL and SUPABASE_SECRET_KEY must be set in backend/.env")
    from supabase import create_client

    return create_client(s.supabase_url, s.supabase_secret_key)


def _one(db: Any, table: str, **eq: Any) -> dict[str, Any] | None:
    q = db.table(table).select("*")
    for k, v in eq.items():
        q = q.eq(k, v)
    rows = q.limit(1).execute().data or []
    return rows[0] if rows else None


def _all(db: Any, table: str, **eq: Any) -> list[dict[str, Any]]:
    q = db.table(table).select("*")
    for k, v in eq.items():
        q = q.eq(k, v)
    return q.execute().data or []


# --- extraction + scoring ------------------------------------------------------
def extract_quote(recap: dict[str, Any], model: str, api_key: str) -> ExtractedQuote:
    from openai import OpenAI

    payload = {
        "summary": recap.get("summary", ""),
        "quoted_prices": recap.get("quoted_prices", []),
        "key_points": recap.get("key_points", []),
        "conditions": recap.get("conditions", []),
        "objections": recap.get("objections", []),
        "agreement_candidates": recap.get("agreement_candidates", []),
    }
    completion = OpenAI(api_key=api_key).chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": EXTRACT_SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        response_format=ExtractedQuote,
    )
    parsed = completion.choices[0].message.parsed
    return parsed or ExtractedQuote()


def to_usd_minor(
    amount: float, currency: str, fx: dict[str, float]
) -> tuple[int | None, str | None]:
    """Returns (usd_minor, note). Needs a rate for anything but USD."""
    currency = currency.upper()
    if currency == "USD":
        return round(amount * 100), None
    rate = fx.get(currency)
    if rate is None:
        return None, f"no FX rate for {currency} (pass --fx {currency}=<usd_per_unit>)"
    return round(amount * rate * 100), f"{amount} {currency} @ {rate} USD/unit"


def window_fit(q: ExtractedQuote, m_start: str | None, m_end: str | None) -> float:
    if not q.pickup_window_start:
        return 0.3  # no committed window is worse than a fitting one, better than a clashing one
    if not (m_start and m_end):
        return 0.7
    try:
        ps = datetime.fromisoformat(q.pickup_window_start.replace("Z", "+00:00"))
        ms = datetime.fromisoformat(m_start)
        me = datetime.fromisoformat(m_end)
    except ValueError:
        return 0.3
    return 1.0 if ms <= ps <= me else 0.0


def score_carriers(carriers: list[Carrier], m_start: str | None, m_end: str | None) -> None:
    priced = [c.usd_minor for c in carriers if c.usd_minor is not None]
    lo, hi = (min(priced), max(priced)) if priced else (0, 0)
    span = (hi - lo) or 1
    for c in carriers:
        q = c.quote or ExtractedQuote()
        norm_price = ((c.usd_minor - lo) / span) if c.usd_minor is not None else 1.0
        n_obj = min(len(q.objections), 4) / 4
        parts = {
            "price": W_PRICE * (1 - norm_price),
            "window": W_WINDOW * window_fit(q, m_start, m_end),
            "objections": W_OBJECTIONS * (1 - n_obj),
            "final": W_FINAL * (1.0 if q.price_is_total_final else 0.0),
            "clarity": W_CLARITY * max(0.0, min(1.0, q.clarity_0_1)),
        }
        if not c.complete:
            parts["incomplete_penalty"] = -INCOMPLETE_PENALTY
        c.score = round(sum(parts.values()), 4)
        c.score_breakdown = {k: round(v, 4) for k, v in parts.items()}


# --- carrier discovery -------------------------------------------------------
def resolve_carriers(
    db: Any, rfq_id: str, assigns: dict[str, str]
) -> tuple[list[Carrier], list[str]]:
    """Only calls tied to THIS RFQ are considered. Returns (carriers, excluded_notes).

    A call belongs to the RFQ when any of:
      * call_cases.metadata->>'rfq_id' == rfq_id           (tag written at/after call time)
      * an offers row links its case_id to this rfq_id
      * it is named in --assign  (an explicit tie; persisted with --commit)
    Anything else with a recap is noise from another case and is excluded, loudly.
    """
    contacts = _all(db, "counterparty_contacts")
    by_phone = {c["phone"]: c for c in contacts}
    by_cp = {c["counterparty_id"]: c for c in contacts}
    cps = {c["id"]: c for c in _all(db, "counterparties")}

    recap_by_sid = {r["call_sid"]: r for r in _all(db, "call_recaps")}
    offers_here = _all(db, "offers", rfq_id=rfq_id)
    cp_by_case = {o["case_id"]: o["counterparty_id"] for o in offers_here if o.get("case_id")}

    carriers: list[Carrier] = []
    excluded: list[str] = []
    for case in _all(db, "call_cases"):
        sid = case["twilio_call_sid"]
        recap = recap_by_sid.get(sid)
        if recap is None:
            continue

        meta = case.get("metadata") or {}
        cp_id: str | None = None
        source = ""
        if assigns.get(sid):
            cp_id, source = assigns[sid], "assign"
        elif meta.get("rfq_id") == rfq_id:
            cp_id, source = meta.get("counterparty_id"), "metadata"
        elif case["id"] in cp_by_case:
            cp_id, source = cp_by_case[case["id"]], "offer"

        if source == "":
            excluded.append(
                f"call {sid} ({case.get('from_number')}) has a recap but is NOT tied to "
                f"RFQ {rfq_id[:8]} — ignored. Tie it with --assign {sid}=<counterparty_id>."
            )
            continue
        if cp_id is None:  # tagged to the RFQ but the carrier is unknown
            for num in (case.get("from_number"), case.get("to_number")):
                if num in by_phone:
                    cp_id = by_phone[num]["counterparty_id"]
                    break
        if cp_id is None:
            excluded.append(f"call {sid} is tied to the RFQ but no carrier — --assign it.")
            continue

        contact = by_cp.get(cp_id)
        cp = cps.get(cp_id, {})
        carriers.append(
            Carrier(
                counterparty_id=cp_id,
                name=cp.get("name", cp_id),
                call_sid=sid,
                case_id=case["id"],
                from_number=case.get("from_number"),
                contact_id=(contact or {}).get("id"),
                contact_name=(contact or {}).get("name"),
                contact_phone=(contact or {}).get("phone"),
                recap=recap,
                tag_source=source,
            )
        )
    return carriers, excluded


# --- email -----------------------------------------------------------------
def _pretty_dt(iso: str | None, fallback: str) -> str:
    if not iso:
        return fallback
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso


def email_template(op_ref: str, container: str, winner: Carrier) -> dict[str, str]:
    q = winner.quote or ExtractedQuote()
    price = (
        f"{q.price_amount:,.0f} {q.price_currency}"
        if q.price_amount is not None and q.price_currency
        else "(por confirmar en la llamada)"
    )
    window = _pretty_dt(q.pickup_window_start, "(por confirmar)")
    who = winner.contact_name or "equipo de despacho"
    body = f"""Estimado/a {who} ({winner.name}),

Gracias por la cotización para la operación {op_ref}, contenedor {container}
(arrastre Contecon Manzanillo → Guadalajara).

Tras comparar las cotizaciones recibidas para este contenedor, su propuesta es la
seleccionada:

  • Tarifa:            {price}
  • Ventana de recogida: {window}
  • Condiciones:        {"; ".join(q.conditions) or "las conversadas en la llamada"}

Esto NO es aún una adjudicación en firme. Para confirmarla necesitamos que respondan a
este correo ratificando la tarifa y la ventana exactas. Una vez recibida su confirmación
por escrito, emitimos la orden para el contenedor {container}.

Quedamos atentos.
"""
    return {
        "to_name": who,
        "to_phone": winner.contact_phone or "",
        "subject": (
            f"{winner.name} — cotización seleccionada, {op_ref} / {container} "
            f"(pendiente de confirmación)"
        ),
        "body": body,
    }


def sms_body(op_ref: str, container: str, winner: Carrier) -> str:
    """Short SMS with the negotiation specs. Only the awarded carrier gets this."""
    q = winner.quote or ExtractedQuote()
    price = (
        f"{q.price_amount:,.0f} {q.price_currency}"
        if q.price_amount is not None and q.price_currency
        else "por confirmar"
    )
    window = _pretty_dt(q.pickup_window_start, "por confirmar")
    conds = "; ".join(q.conditions)
    msg = (
        f"{winner.name}: seleccionados para contenedor {container} ({op_ref}), "
        f"Contecon Manzanillo -> Guadalajara. Tarifa: {price}. Recogida: {window}."
    )
    if conds:
        msg += f" Condiciones: {conds}."
    msg += " Responda SI para confirmar. Aun no es adjudicacion en firme."
    return msg


def send_sms(to_phone: str, body: str) -> dict[str, str]:
    """Send one SMS via Twilio. Returns {status, sid|error}."""
    s = get_settings()
    if not (s.twilio_account_sid and s.twilio_auth_token and s.twilio_phone_number):
        return {"status": "skipped", "error": "Twilio credentials not set in backend/.env"}
    if not to_phone:
        return {"status": "skipped", "error": "the awarded carrier's contact has no phone"}
    from twilio.rest import Client

    try:
        msg = Client(s.twilio_account_sid, s.twilio_auth_token).messages.create(
            to=to_phone, from_=s.twilio_phone_number, body=body
        )
    except Exception as exc:  # noqa: BLE001 — surface any Twilio error, do not crash the award
        return {"status": "failed", "error": str(exc)[:300]}
    return {"status": "sent", "sid": str(msg.sid)}


# --- report + writes ---------------------------------------------------------
def print_report(carriers: list[Carrier], ranked: list[Carrier], cap_usd_minor: int | None) -> None:
    print("\n" + "=" * 78)
    print("RANKING")
    print("=" * 78)
    for i, c in enumerate(ranked, 1):
        q = c.quote or ExtractedQuote()
        usd = f"${c.usd_minor / 100:,.2f}" if c.usd_minor is not None else "  —  "
        raw = (
            f"{q.price_amount:,.0f} {q.price_currency}"
            if q.price_amount is not None and q.price_currency
            else "sin cifra/moneda"
        )
        flag = "" if c.complete else "  [INCOMPLETE]"
        mand = (
            ""
            if c.within_mandate is None
            else ("  ✓dentro" if c.within_mandate else "  ✗sobre cap")
        )
        print(f"  {i}. {c.name:<24} score {c.score:+.3f}  {usd:>12}  ({raw}){flag}{mand}")
        print(f"      {c.score_breakdown}")
        if q.objections:
            print(f"      objeciones: {len(q.objections)} · {q.notes}")
    if cap_usd_minor is not None:
        print(f"\n  mandato cap: ${cap_usd_minor / 100:,.2f} USD")


def do_writes(
    db: Any,
    *,
    tenant_id: str,
    operation_id: str,
    rfq_id: str,
    mandate_id: str,
    carriers: list[Carrier],
    winner: Carrier,
    reason: str,
    fx: dict[str, float],
    commit: bool,
) -> str | None:
    tag = "WRITE" if commit else "dry-run — WOULD WRITE"
    print("\n" + "=" * 78)
    print(tag)
    print("=" * 78)

    # offers_check: a non-USD amount needs an fx_rate_snapshots row.
    now = datetime.now(UTC)
    snap_by_cur: dict[str, str] = {}
    for c in carriers:
        cur = (c.quote.price_currency or "").upper() if c.quote else ""
        if c.usd_minor is None or cur in ("", "USD") or cur in snap_by_cur:
            continue
        snap = {
            "provider": "manual",
            "quote_currency": cur,
            "usd_per_unit": fx[cur],
            "observed_at": now.isoformat(),
            "expires_at": now.replace(year=now.year + 1).isoformat(),
        }
        print(f"  fx_rate_snapshots <- {json.dumps(snap, ensure_ascii=False)}")
        if commit:
            snap_by_cur[cur] = db.table("fx_rate_snapshots").insert(snap).execute().data[0]["id"]
        else:
            snap_by_cur[cur] = f"<fx:{cur}>"
    for c in carriers:
        cur = (c.quote.price_currency or "").upper() if c.quote else ""
        c.fx_snapshot_id = snap_by_cur.get(cur)

    offer_ids: dict[str, str] = {}
    for c in carriers:
        row = {
            "tenant_id": tenant_id,
            "rfq_id": rfq_id,
            "counterparty_id": c.counterparty_id,
            "case_id": c.case_id,
            "quoted_currency": (c.quote.price_currency or "XXX").upper() if c.quote else "XXX",
            "policy_amount_usd_minor": c.usd_minor,
            "fx_snapshot_id": c.fx_snapshot_id,
            "mandate_id": mandate_id,
            "pickup_window_start": (c.quote.pickup_window_start if c.quote else None),
            "pickup_window_end": (c.quote.pickup_window_end if c.quote else None),
            "is_total_final": bool(c.quote and c.quote.price_is_total_final),
            "status": "proposed",
        }
        print(f"  offers <- {c.name}: {json.dumps(row, ensure_ascii=False)}")
        if commit:
            offer_ids[c.counterparty_id] = db.table("offers").insert(row).execute().data[0]["id"]

    seg = {
        "case_id": winner.case_id,
        "offset_from_ms": 0,
        "claimed_identity": winner.name,
        "identity_level": 1,
        "resolved_contact_id": winner.contact_id,
    }
    print(f"  participant_segments <- winner: {json.dumps(seg, ensure_ascii=False)}")
    seg_id = None
    if commit:
        seg_id = db.table("participant_segments").insert(seg).execute().data[0]["id"]

    print(f"  rfqs.phase: open -> awarding  ({rfq_id})")
    if commit:
        db.table("rfqs").update({"phase": "awarding"}).eq("id", rfq_id).execute()

    commitment = {
        "tenant_id": tenant_id,
        "operation_id": operation_id,
        "offer_id": offer_ids.get(winner.counterparty_id, "<offer_id>"),
        "participant_segment_id": seg_id or "<participant_segment_id>",
        "chain_state": "VERBAL",
    }
    print(f"  commitments <- winner: {json.dumps(commitment, ensure_ascii=False)}")
    commitment_id = None
    if commit:
        commitment_id = db.table("commitments").insert(commitment).execute().data[0]["id"]
        db.table("offers").update({"status": "accepted"}).eq(
            "id", offer_ids[winner.counterparty_id]
        ).execute()
        for cp_id, oid in offer_ids.items():
            if cp_id != winner.counterparty_id:
                db.table("offers").update({"status": "rejected"}).eq("id", oid).execute()

    transition = {
        "commitment_id": commitment_id or "<commitment_id>",
        "to_state": "VERBAL",
        "actor": "nauta-award-script",
        "reason": reason[:500],
    }
    print(f"  commitment_transitions <- {json.dumps(transition, ensure_ascii=False)}")
    if commit:
        db.table("commitment_transitions").insert(transition).execute()
        print(f"\n  committed: commitment {commitment_id}")
    return commitment_id


# --- main -----------------------------------------------------------------
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--operation-ref", default="OP-MZO-0001")
    p.add_argument("--rfq", help="RFQ id; defaults to the newest RFQ of the operation")
    p.add_argument(
        "--assign",
        action="append",
        default=[],
        metavar="CALL_SID=COUNTERPARTY_ID",
        help="tie a call to a carrier for this RFQ; with --commit it is saved to "
        "call_cases.metadata so later runs need no flag",
    )
    p.add_argument(
        "--fx",
        action="append",
        default=[],
        metavar="CUR=USD_PER_UNIT",
        help="FX rate for a non-USD quote, e.g. --fx MXN=0.058",
    )
    p.add_argument("--commit", action="store_true", help="actually write to Supabase")
    p.add_argument(
        "--sms",
        action="store_true",
        help="after committing, SMS the negotiation specs to the awarded carrier only "
        "(requires --commit)",
    )
    p.add_argument(
        "--force-incomplete",
        action="store_true",
        help="allow awarding a carrier whose recap has no confirmed price",
    )
    args = p.parse_args()
    if args.sms and not args.commit:
        return _fail("--sms notifies the carrier of a recorded award; pass --commit too")

    settings = get_settings()
    fx = {k.upper(): float(v) for k, v in (a.split("=", 1) for a in args.fx)}
    assigns = dict(a.split("=", 1) for a in args.assign)

    db = _db()
    op = _one(db, "operations", reference=args.operation_ref)
    if not op:
        return _fail(f"no operation with reference {args.operation_ref!r}")
    rfq = (
        _one(db, "rfqs", id=args.rfq)
        if args.rfq
        else max(
            _all(db, "rfqs", operation_id=op["id"]), key=lambda r: r["created_at"], default=None
        )
    )
    if not rfq:
        return _fail(f"operation {args.operation_ref} has no RFQ")
    mandate = _one(db, "mandates", operation_id=op["id"], status="active")
    m_start = mandate.get("window_start") if mandate else None
    m_end = mandate.get("window_end") if mandate else None
    cap_usd_minor = (
        int(mandate["cap_amount_minor"])
        if mandate and mandate.get("cap_currency") == "USD"
        else None
    )

    container = (op.get("vertical_payload") or {}).get("container_number") or "(sin número)"
    print(
        f"operation {op['reference']}  container {container}  rfq {rfq['id']}  phase={rfq['phase']}"
    )

    carriers, excluded = resolve_carriers(db, rfq["id"], assigns)
    for ex_note in excluded:
        print(f"  excluded: {ex_note}", file=sys.stderr)
    if not carriers:
        return _fail(
            "no call is tied to this RFQ. Tie each carrier call with "
            "--assign CALL_SID=COUNTERPARTY_ID (add --commit to persist the tag)."
        )
    print(f"carriers in this quotation process: {len(carriers)}")
    for c in carriers:
        print(f"  - {c.name}  (call {c.call_sid[:12]}…, tied via {c.tag_source})")

    # Persist any --assign as a durable tag on the call, so the next run needs no flags
    # and nothing from another container can leak into this comparison.
    if assigns:
        for c in carriers:
            if c.tag_source != "assign":
                continue
            tag = {
                "rfq_id": rfq["id"],
                "operation_ref": op["reference"],
                "counterparty_id": c.counterparty_id,
                "container_number": container,
            }
            print(f"  {'tag' if args.commit else 'would tag'} call_cases {c.call_sid}: {tag}")
            if args.commit:
                db.table("call_cases").update(
                    {
                        "metadata": {
                            **(_one(db, "call_cases", twilio_call_sid=c.call_sid) or {}).get(
                                "metadata", {}
                            ),
                            **tag,
                        }
                    }
                ).eq("twilio_call_sid", c.call_sid).execute()

    for c in carriers:
        c.quote = extract_quote(c.recap, settings.openai_agent_model, settings.openai_api_key)
        q = c.quote
        if q.price_amount is not None and q.price_currency:
            c.usd_minor, note = to_usd_minor(q.price_amount, q.price_currency, fx)
            c.fx_snapshot_id = None  # filled at write time if a snapshot is created
            c.complete = c.usd_minor is not None
            if note:
                print(f"  {c.name}: {note}")
        else:
            c.complete = False
        if c.usd_minor is not None and cap_usd_minor is not None:
            c.within_mandate = c.usd_minor <= cap_usd_minor

    score_carriers(carriers, m_start, m_end)
    ranked = sorted(carriers, key=lambda c: c.score, reverse=True)
    print_report(carriers, ranked, cap_usd_minor)

    top = ranked[0]
    eligible = [c for c in ranked if c.complete and (c.within_mandate is not False)]
    winner = eligible[0] if eligible else None

    if winner is None:
        print("\nNo carrier is awardable: none has a confirmed, within-mandate price.")
        print("Recall the carriers and re-run. Nothing written.")
        return 2
    if top is not winner and not args.force_incomplete:
        print(
            f"\nTop-ranked is {top.name} but its recap is incomplete / over cap. "
            f"Best awardable is {winner.name}. "
            f"Pass --force-incomplete to award the top-ranked anyway."
        )
    award = top if (args.force_incomplete and top.complete) else winner

    reason = (
        f"score {award.score:+.3f}; "
        f"${(award.usd_minor or 0) / 100:,.2f} USD; "
        f"objeciones={len((award.quote or ExtractedQuote()).objections)}; "
        f"final={bool(award.quote and award.quote.price_is_total_final)}; "
        f"vs {len(carriers)} carriers"
    )
    print(f"\nWINNER: {award.name}  —  {reason}")

    mail = email_template(op["reference"], container, award)
    print("\n" + "=" * 78 + "\nEMAIL TEMPLATE (draft — not sent)\n" + "=" * 78)
    print(f"To:      {mail['to_name']}  <{mail['to_phone']}>")
    print(f"Subject: {mail['subject']}\n")
    print(mail["body"])

    artifact = {
        "generated_at": datetime.now(UTC).isoformat(),
        "operation": op["reference"],
        "container_number": container,
        "rfq_id": rfq["id"],
        "carriers_in_process": len(carriers),
        "excluded_calls": excluded,
        "mandate_cap_usd_minor": cap_usd_minor,
        "winner": award.name,
        "reason": reason,
        "ranking": [
            {
                "carrier": c.name,
                "call_sid": c.call_sid,
                "tied_via": c.tag_source,
                "score": c.score,
                "breakdown": c.score_breakdown,
                "usd_minor": c.usd_minor,
                "complete": c.complete,
                "within_mandate": c.within_mandate,
                "quote": (c.quote.model_dump() if c.quote else None),
            }
            for c in ranked
        ],
        "email_template": mail,
    }
    out = pathlib.Path.cwd() / f"nauta_award_{rfq['id'][:8]}.json"
    out.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")

    if mandate is None:
        return _fail("operation has no active mandate — cannot award")
    commitment_id = do_writes(
        db,
        tenant_id=op["tenant_id"],
        operation_id=op["id"],
        rfq_id=rfq["id"],
        mandate_id=mandate["id"],
        carriers=carriers,
        winner=award,
        reason=reason,
        fx=fx,
        commit=args.commit,
    )

    # SMS — only the awarded carrier, only once its commitment row exists.
    body = sms_body(op["reference"], container, award)
    print("\n" + "=" * 78 + "\nSMS TO AWARDED CARRIER\n" + "=" * 78)
    print(f"To:   {award.contact_name or '(sin contacto)'}  <{award.contact_phone or '—'}>")
    print(f"Body: {body}")
    sms_result: dict[str, str] = {"status": "not-sent (no --sms)"}
    if args.sms and commitment_id:
        sms_result = send_sms(award.contact_phone or "", body)
        print(f"      -> {sms_result}")
    elif args.sms:
        print("      -> skipped: no commitment was written")

    artifact["sms"] = {"to": award.contact_phone, "body": body, "result": sms_result}
    out.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.commit:
        print("\n(dry run — pass --commit to write, and --commit --sms to notify)")
    return 0


def _fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

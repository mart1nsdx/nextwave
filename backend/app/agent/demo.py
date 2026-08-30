"""Mocked business data for the demo lane. The only file that invents a company.

Stands in for the pre-registration a human writes in the dashboard and that repo/ will
read back per call. It is *data*, not a prompt: the instruction text is composed per call
in prompts.py from this profile plus the phase and today's date, so a demo call and a real
one take the same code path. Delete this module the moment repo/ can return a profile —
and do not add a second one, because two mocks drift.

The company and the lane are the scenario in docs/CHALLENGE.md. Change them here and the
whole call changes; there is no other place a company name is written.
"""

from decimal import Decimal

from app.domain import CompanyProfile

from .context import CallContext, CallPhase
from .prompts import today_for

__all__ = ["DEMO_PROFILE", "demo_context"]

DEMO_PROFILE = CompanyProfile(
    display_name="Textiles Pacífico",
    business_type="importer",
    city="Guadalajara",
    country="México",
    commodities=["textiles", "telas en rollo"],
    equipment=["chasis para contenedor de 40 pies"],
    currency="MXN",
    timezone="America/Mexico_City",
    # Overridden away from the en / es-CO default: this lane is Mexican, and the register a
    # dispatcher in Manzanillo expects is not the one a dispatcher in Bogotá expects.
    primary_language="es-MX",
    fallback_language="en",
    recap_channel="sms",
)

# The ceiling matches docs/UGLY_CASES.md row 1 on purpose — the judge says "your boss
# approved 10,500" against a cap of 9,000 — so the hostile fixtures and the demo prompt
# cannot drift apart.
_CEILING = Decimal("9000")
_TARGET = Decimal("8200")


def demo_context(phase: CallPhase) -> CallContext:
    """The operation one call is about, for a phase chosen by the caller, not by the model.

    `today` is read here rather than written down, because a frozen date is the quietest
    way to break invariant #8: the agent resolves "el jueves" against it, so a stale value
    produces a confident, wrong, read-back calendar date instead of a question.
    """
    return CallContext(
        phase=phase,
        today=today_for(DEMO_PROFILE),
        reference="OP-1042",
        origin="Manzanillo",
        destination="nuestra bodega en Guadalajara",
        cargo="un contenedor de 40 pies con textiles",
        equipment="chasis de 40 pies",
        pickup_window="entre el martes 2 y el jueves 4 de septiembre de 2026",
        price_ceiling=_CEILING,
        target_price=_TARGET,
        # Inbound only: what a legitimate caller can tell us and an impostor cannot. The
        # agent checks answers against it and never reads it out (prompts.py, _INBOUND).
        expected_carrier="Transportes del Bajío" if phase is CallPhase.INBOUND else None,
    )

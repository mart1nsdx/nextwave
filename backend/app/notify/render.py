"""Render a Recap into an email. Wording only — no authority, no decisions.

The email restates what was said on the call so both sides have a written record. It does
not assert that anything is booked; that word belongs to the state machine.
"""

from __future__ import annotations

from html import escape

from app.domain.models import Recap


def subject(recap: Recap) -> str:
    return f"Resumen de llamada — {recap.call_sid}"


def _section(title: str, items: list[str]) -> tuple[str, str]:
    if not items:
        return "", ""
    text = f"\n{title}:\n" + "".join(f"  - {i}\n" for i in items)
    html = (
        f"<h3 style='margin:16px 0 4px'>{escape(title)}</h3><ul>"
        + "".join(f"<li>{escape(i)}</li>" for i in items)
        + "</ul>"
    )
    return text, html


def bodies(recap: Recap) -> tuple[str, str]:
    """Return (plain_text, html)."""

    sections = [
        ("Puntos clave", recap.key_points),
        ("Precios mencionados", recap.quoted_prices),
        ("Nombres", recap.names),
        ("Condiciones", recap.conditions),
        ("Objeciones", recap.objections),
        ("Cambios durante la llamada", recap.changes),
    ]
    rendered = [_section(title, items) for title, items in sections]

    text = (
        f"Resumen de la llamada {recap.call_sid}\n\n{recap.summary}\n"
        + "".join(t for t, _ in rendered)
        + "\nEste correo es un registro de lo conversado. No constituye una reserva "
        "confirmada hasta su verificación interna.\n"
    )
    html = (
        f"<div style='font-family:system-ui,sans-serif;max-width:640px'>"
        f"<h2 style='margin:0 0 8px'>Resumen de la llamada {escape(recap.call_sid)}</h2>"
        f"<p>{escape(recap.summary)}</p>"
        + "".join(h for _, h in rendered)
        + "<p style='color:#666;font-size:13px;margin-top:20px'>Este correo es un "
        "registro de lo conversado. No constituye una reserva confirmada hasta su "
        "verificación interna.</p></div>"
    )
    return text, html

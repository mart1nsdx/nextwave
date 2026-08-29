"""Replay a recorded transcript through the evidence + recap path — no PSTN, no Twilio.

    uv run python -m scripts.sim_call --scenario manzanillo_guadalajara

The transcription leg (Twilio audio -> OpenAI Realtime) is skipped: the fixture already
holds what would have been transcribed. Everything after it is exercised for real —
ledger append, ordering, idempotency, and the recap/brief generation.

The ledger path costs nothing. The recap runs only if OPENAI_API_KEY is set; otherwise
the assembled transcript is printed and recap generation is skipped.

Tests never place a real outbound call (AGENTS.md). This is how a scenario gets exercised.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.agent import OpenAIRecapModel
from app.config import get_settings
from app.domain.models import (
    CallDirection,
    RecapContext,
    Speaker,
    TranscriptTrack,
)
from app.ledger import EvidenceLedger
from app.main import RecapService, _build_sender
from app.repo import InMemoryTranscriptStore

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "transcripts"


def _scenarios() -> list[str]:
    return sorted(p.stem for p in FIXTURES.glob("*.json"))


async def _run(scenario: str) -> int:
    fixture = json.loads((FIXTURES / f"{scenario}.json").read_text())
    call_sid = fixture["call_sid"]

    store = InMemoryTranscriptStore()
    ledger = EvidenceLedger(store)
    await store.open_case(
        call_sid,
        CallDirection(fixture.get("direction", "inbound")),
        from_number=fixture.get("from_number"),
        to_number=fixture.get("to_number"),
    )

    for i, seg in enumerate(fixture["segments"], start=1):
        await ledger.record_segment(
            call_sid,
            track=TranscriptTrack(seg["track"]),
            sequence_number=i,
            audio_offset_ms=seg["audio_offset_ms"],
            text=seg["text"],
            is_final=True,
            speaker=Speaker(seg.get("speaker", "unknown")),
        )
    await store.close_case(call_sid)

    print(f"=== transcript ({call_sid}) ===")
    print(await ledger.transcript_text(call_sid))
    print(f"\nhas_audio_anchor: {await ledger.has_audio_anchor(call_sid)}")

    settings = get_settings()
    if not settings.openai_api_key:
        print("\nOPENAI_API_KEY not set — recap generation skipped.")
        return 0

    model = OpenAIRecapModel(settings.openai_api_key, settings.openai_recap_model)
    service = RecapService(
        ledger,
        store,
        model,
        _build_sender(settings),
        default_to_email=settings.recap_to_email,
    )
    context = RecapContext.model_validate(fixture.get("context", {}))
    await service.run(call_sid, context=context)

    recap = await store.get_recap(call_sid)
    brief = await store.get_brief(call_sid)
    delivery = await store.get_recap_delivery(call_sid)
    print(f"\n=== recap (model {recap.model if recap else '?'}) ===")
    print(recap.model_dump_json(indent=2) if recap else "(none)")
    print("\n=== brief ===")
    print(brief.model_dump_json(indent=2) if brief else "(none)")
    print("\n=== recap delivery ===")
    print(delivery.model_dump_json(indent=2) if delivery else "(none)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, choices=_scenarios())
    args = parser.parse_args()
    return asyncio.run(_run(args.scenario))


if __name__ == "__main__":
    raise SystemExit(main())

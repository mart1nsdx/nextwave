"""Per-turn latency evidence, separated from transcript and authorization data."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TurnLatency:
    """One completed or interrupted reply measured with a monotonic process clock."""

    turn: int
    evidence: str
    utterance_end_offset_ms: int
    stt_endpoint_ms: float
    model_first_chunk_ms: float | None
    tts_first_audio_ms: float | None
    end_to_end_first_audio_ms: float | None
    response_complete_ms: float | None
    interrupted: bool


@dataclass(slots=True)
class ActiveTurnLatency:
    turn: int
    evidence: str
    utterance_end_offset_ms: int
    started_at: float
    stt_endpoint_ms: float
    model_first_chunk_at: float | None = None
    tts_first_audio_at: float | None = None
    response_complete_at: float | None = None

    def finish(self, now: float, *, interrupted: bool) -> TurnLatency:
        return TurnLatency(
            turn=self.turn,
            evidence=self.evidence,
            utterance_end_offset_ms=self.utterance_end_offset_ms,
            stt_endpoint_ms=self.stt_endpoint_ms,
            model_first_chunk_ms=_elapsed(self.started_at, self.model_first_chunk_at),
            tts_first_audio_ms=_elapsed(self.model_first_chunk_at, self.tts_first_audio_at),
            end_to_end_first_audio_ms=_elapsed(self.started_at, self.tts_first_audio_at),
            response_complete_ms=(
                None if interrupted else _elapsed(self.started_at, self.response_complete_at or now)
            ),
            interrupted=interrupted,
        )


def _elapsed(start: float | None, end: float | None) -> float | None:
    if start is None or end is None:
        return None
    return round(max(0.0, (end - start) * 1000), 1)

"""Mu-law framing and the local barge-in gate. Pure — no network, no audio files."""

from app.voice.frames import BYTES_PER_SECOND, FRAME_BYTES, MULAW_DECODE, SILENCE_BYTE
from app.voice.vad import EnergyVad, VadSettings, frame_rms

LOUD = bytes([0x00, 0x80] * (FRAME_BYTES // 2))  # alternating full-scale +/- 32124
SILENT = bytes([SILENCE_BYTE]) * FRAME_BYTES
# +/-876 RMS: audible line/background noise, but below the production speech gate.
NOISY = bytes([0xD0, 0x50] * (FRAME_BYTES // 2))


def test_mulaw_table_matches_g711_reference_points() -> None:
    # The four values the G.711 spec pins down. If these drift, every RMS reading and
    # therefore every barge-in threshold is silently wrong.
    assert MULAW_DECODE[0xFF] == 0
    assert MULAW_DECODE[0x7F] == 0
    assert MULAW_DECODE[0x00] == -32124
    assert MULAW_DECODE[0x80] == 32124
    assert len(MULAW_DECODE) == 256


def test_frame_geometry_matches_twilio() -> None:
    assert FRAME_BYTES == 160  # 20 ms at 8 kHz, one byte per sample
    assert BYTES_PER_SECOND == 8000


def test_silence_is_not_zero_bytes() -> None:
    # The classic mu-law bug: zeroing a buffer produces full-scale noise, not silence.
    assert frame_rms(SILENT) == 0.0
    assert frame_rms(bytes(FRAME_BYTES)) > 30000


def test_barge_in_needs_sustained_speech_not_one_loud_frame() -> None:
    """A cough is not an interruption. 120 ms of speech is."""
    vad = EnergyVad(VadSettings(barge_in_min_ms=120))
    # 120 ms at 20 ms per frame = the sixth frame, not the first.
    assert [vad.feed(LOUD) for _ in range(5)] == [False] * 5
    assert vad.feed(LOUD) is True


def test_prolonged_background_noise_does_not_trigger_the_production_gate() -> None:
    settings = VadSettings()
    vad = EnergyVad(settings)
    assert frame_rms(NOISY) < settings.barge_in_rms_threshold
    assert not any(vad.feed(NOISY) for _ in range(100))


def test_barge_in_latches_so_the_cut_happens_once() -> None:
    vad = EnergyVad(VadSettings(barge_in_min_ms=40))
    fired = [vad.feed(LOUD) for _ in range(6)]
    assert fired.count(True) == 1, "one interruption must not produce six cuts"


def test_silence_resets_the_accumulator() -> None:
    vad = EnergyVad(VadSettings(barge_in_min_ms=120))
    for _ in range(5):
        vad.feed(LOUD)
    vad.feed(SILENT)
    assert vad.voiced_ms == 0.0
    assert [vad.feed(LOUD) for _ in range(5)] == [False] * 5, "must re-earn the 120 ms"
    assert vad.feed(LOUD) is True


def test_disabled_barge_in_never_fires() -> None:
    vad = EnergyVad(VadSettings(barge_in_enabled=False, barge_in_min_ms=0))
    assert not any(vad.feed(LOUD) for _ in range(50))

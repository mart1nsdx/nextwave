"""Settings. The only module in the codebase that reads the environment.

MAY IMPORT:  stdlib, pydantic-settings. Nothing from app.
IMPORTED BY: repo, notify, voice, telephony, main.

A leaf, like domain/. Centralised so that a missing key fails loudly at startup rather
than three hours later, mid-call, when the recap tries to send.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Telephony (Twilio) ---
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""
    validate_twilio_signature: bool = True

    # --- Reasoning (OpenAI, via the Agents SDK) ---
    openai_api_key: str = ""
    # Not hardcoded: model ids move, and most tutorials online are stale. Verify the
    # current fast model id against OpenAI's docs before filling this in.
    openai_agent_model: str = ""
    openai_recap_model: str = ""

    # --- Speech ---
    deepgram_api_key: str = ""
    # "deepgram" | "fake". The fake providers are how sim_call and the test suite run
    # the whole pipeline with no network and no cost.
    stt_provider: str = "deepgram"
    stt_model: str = "nova-3"
    # "multi" enables ES/EN code-switching within a single utterance, which the judge
    # is likely to do. A single-language code (es, en) is the alternative.
    stt_language: str = "multi"
    # Aliases for the post-call evidence path. They default to the live STT settings.
    deepgram_model: str = "nova-3"
    deepgram_language: str = "multi"
    tts_provider: str = "deepgram"
    # Aura-2 voices that switch between English and Spanish: aquila, carina, diana,
    # javier, selena. Use aura-2-estrella-es for Mexican-accented Spanish only.
    tts_model: str = "aura-2-carina-es"

    # --- Turn-taking / VAD ---
    # Two different questions, answered by two different mechanisms. See voice/vad.py.
    # Turn end (did they *finish*?) is the speech vendor's endpointer: it needs
    # linguistic accuracy and can afford a network round-trip.
    vad_endpointing_ms: int = 100  # Deepgram's recommended value for code-switching
    vad_utterance_end_ms: int = 1000
    # Barge-in (did they *start* while we were talking?) is local, because a round-trip
    # here means the agent talks over the counterparty for a third of a second.
    vad_barge_in_enabled: bool = True
    vad_barge_in_rms_threshold: float = 900.0  # int16 RMS; calibrate against a real line
    vad_barge_in_min_ms: int = 120  # consecutive voiced audio; filters coughs and line noise
    vad_min_silence_before_reply_ms: int = 250

    # --- Escalation and callbacks ---
    supabase_url: str = ""
    supabase_secret_key: str = ""
    escalation_phone_number: str = ""
    sendgrid_api_key: str = ""
    recap_from_email: str = ""
    recap_from_name: str = "Volta"
    recap_to_email: str = ""
    public_base_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()

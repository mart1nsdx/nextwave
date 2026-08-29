"""Settings. The only module in the codebase that reads the environment.

MAY IMPORT:  stdlib, pydantic-settings. Nothing from app.
IMPORTED BY: repo, notify, realtime, telephony, main.

A leaf, like domain/. Centralised so that a missing key fails loudly at startup rather
than three hours later, mid-call, when the recap tries to send.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""
    openai_api_key: str = ""
    # Not hardcoded: the Realtime beta interface was removed 2026-05-12 and model ids
    # move. Verify the current id before pinning it in .env.
    openai_realtime_model: str = ""
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    escalation_phone_number: str = ""
    public_base_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""Settings. The only module in the codebase that reads the environment.

MAY IMPORT:  stdlib, pydantic-settings. Nothing from app.
IMPORTED BY: repo, notify, realtime, telephony, main.

A leaf, like domain/. Centralised so that a missing key fails loudly at startup rather
than three hours later, mid-call, when the recap tries to send.

Scope: the call -> transcript -> Supabase -> recap -> email path. Other modules add
their own keys here as they need them (outbound Twilio, the voice agent, escalation).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Twilio: inbound webhook signature + Media Streams. Only the auth token is needed
    # to validate; the account SID and outbound number belong to the outbound-call path.
    twilio_auth_token: str = ""
    # When set, the inbound call is bridged to this number so both legs have audio.
    forward_to_number: str = ""
    # Only false while testing a local tunnel. Always true in production.
    validate_twilio_signature: bool = True

    # Deepgram: streaming speech-to-text. Takes Twilio's mu-law 8 kHz directly.
    deepgram_api_key: str = ""
    deepgram_model: str = "nova-3"
    # "multi" lets the model code-switch (Spanish/English on the same call).
    deepgram_language: str = "multi"

    # OpenAI: the recap + brief chat model (structured outputs). "gpt-5.6" is OpenAI's
    # current API recommendation (Aug 2026); override in .env if that has moved again.
    openai_api_key: str = ""
    openai_recap_model: str = "gpt-5.6"

    # SendGrid (Twilio Email): delivers the written recap. A commitment does not count
    # until this send succeeds (AGENTS.md invariant #3).
    sendgrid_api_key: str = ""
    recap_from_email: str = ""
    recap_from_name: str = "Volta"
    # Default recipient when a call has no operation-level contact yet.
    recap_to_email: str = ""

    supabase_url: str = ""
    supabase_service_role_key: str = ""

    # Public HTTPS domain Twilio calls back into (e.g. an ngrok URL).
    public_base_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()

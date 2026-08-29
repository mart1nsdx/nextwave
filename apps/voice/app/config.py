"""Configuration references only environment variables; no secrets live here."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class Settings:
    twilio_auth_token: str
    public_base_url: str
    forward_to_number: str
    validate_twilio_signature: bool

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "").rstrip("/"),
            forward_to_number=os.getenv("FORWARD_TO_NUMBER", ""),
            validate_twilio_signature=os.getenv("VALIDATE_TWILIO_SIGNATURE", "true").lower() == "true",
        )

    def url_for(self, path: str, *, websocket: bool = False) -> str:
        if not self.public_base_url:
            raise RuntimeError("PUBLIC_BASE_URL must contain the public HTTPS domain")
        parsed = urlparse(self.public_base_url)
        return parsed._replace(
            scheme="wss" if websocket else "https",
            path=path,
            params="",
            query="",
            fragment="",
        ).geturl()

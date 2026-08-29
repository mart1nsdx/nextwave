"""Point the Twilio number at the ngrok tunnel that is running right now.

    uv run python -m scripts.point_number

The ngrok URL changes on every restart, and a stale webhook does not raise anything —
inbound calls just 404 and the caller hears silence. That failure is invisible until a
judge dials in, so re-pointing is a command rather than a checklist item.

Reads the live tunnel from ngrok's local API, updates the number, and writes
PUBLIC_BASE_URL into .env so the server and the webhook can never disagree.

    --echo   point the number at the echo diagnostic instead of the agent
"""

import argparse
import pathlib
import sys

import httpx
from twilio.rest import Client

from app.config import get_settings

NGROK_API = "http://127.0.0.1:4040/api/tunnels"
ENV_FILE = pathlib.Path(__file__).resolve().parent.parent / ".env"


def current_tunnel() -> str:
    try:
        tunnels = httpx.get(NGROK_API, timeout=3.0).json()["tunnels"]
    except (httpx.HTTPError, KeyError) as unreachable:
        raise SystemExit(
            f"Cannot reach ngrok's local API at {NGROK_API} ({unreachable}). "
            "Start it first:  ngrok http 8000"
        ) from unreachable

    for tunnel in tunnels:
        url = tunnel.get("public_url", "")
        if url.startswith("https://"):
            return str(url)
    raise SystemExit("ngrok is running but has no https tunnel. Try: ngrok http 8000")


def write_public_base_url(url: str) -> None:
    """Keep .env in step with the tunnel, so the two can never disagree."""
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    updated = [
        f"PUBLIC_BASE_URL={url}" if line.startswith("PUBLIC_BASE_URL=") else line for line in lines
    ]
    if not any(line.startswith("PUBLIC_BASE_URL=") for line in lines):
        updated.append(f"PUBLIC_BASE_URL={url}")
    ENV_FILE.write_text("\n".join(updated) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--echo",
        action="store_true",
        help="route the number to the echo diagnostic instead of the agent",
    )
    args = parser.parse_args()

    settings = get_settings()
    for key in ("twilio_account_sid", "twilio_auth_token", "twilio_phone_number"):
        if not getattr(settings, key):
            print(f"{key.upper()} is empty in .env — cannot reach Twilio.", file=sys.stderr)
            return 1

    base = current_tunnel()
    voice_path = "/twilio/voice/echo" if args.echo else "/twilio/voice"

    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    matches = client.incoming_phone_numbers.list(phone_number=settings.twilio_phone_number)
    if not matches:
        print(
            f"{settings.twilio_phone_number} is not a number on this Twilio account.",
            file=sys.stderr,
        )
        return 1

    matches[0].update(
        voice_url=f"{base}{voice_path}",
        voice_method="POST",
        status_callback=f"{base}/twilio/status",
        status_callback_method="POST",
    )
    write_public_base_url(base)

    print(f"{settings.twilio_phone_number}  ->  {base}{voice_path}")
    print(f"PUBLIC_BASE_URL={base}  written to .env")
    print("\nRestart the server so it picks up the new URL, then call the number.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

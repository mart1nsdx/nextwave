# nextwave

## Voice service architecture

`apps/voice` receives inbound Twilio calls and forks their audio through
Twilio Media Streams. It deliberately has no database or stored credentials.

```text
Twilio phone number -> POST /voice -> TwiML <Start><Stream>
                                      -> WSS /media -> STT adapter
```

The adapter currently logs the integration boundary only. The next change will
implement a specific streaming speech-to-text vendor without changing the
Twilio-facing code.

### Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn apps.voice.app.main:app --host 0.0.0.0 --port 8000
```

Expose the service with a public HTTPS/WSS tunnel, set `PUBLIC_BASE_URL` to
that address, and configure the Twilio number to make a `POST` request to
`https://YOUR_DOMAIN/voice` when a call arrives.

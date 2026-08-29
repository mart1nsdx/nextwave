# Twilio inbound transcription service

| Route | Purpose |
| --- | --- |
| `POST /voice` | Validated webhook that produces the TwiML call flow. |
| `WSS /media` | Validated Twilio Media Stream receiver. |
| `POST /stream-status` | Auditable stream start, stop, and error events. |

Twilio sends base64-encoded `audio/x-mulaw`, 8 kHz, mono frames. The service
passes those frames to the `StreamingTranscriber` interface; its initial
implementation does not save or transcribe audio yet.

"""The voice pipeline: STT -> LLM -> TTS, plus turn-taking, VAD, and barge-in.

MAY IMPORT:  domain, config, agent, tools.
IMPORTED BY: telephony.

Vendor boundary for *speech* — distinct from telephony/, which is the vendor boundary
for the *audio transport*. Two providers, two failure modes, two directories: Twilio
drops frames and redelivers webhooks; a speech vendor changes model ids and session
semantics. See docs/DECISION_LOG.md D7 for why this is a cascade (STT -> LLM -> TTS)
rather than OpenAI's speech-to-speech Realtime API.

Nothing here knows Twilio exists. The pipeline consumes and produces mu-law 8 kHz
frames through the Protocols in voice/frames.py, which is what lets it run against a
fake transport in tests with no PSTN leg and no cost.

Model ids and provider names come from config; never hardcode one here.
"""

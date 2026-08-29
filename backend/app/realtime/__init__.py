"""OpenAI Realtime session: turn handling, tool dispatch, barge-in response.

MAY IMPORT:  domain, config, agent, tools.
IMPORTED BY: telephony.

Vendor boundary for the *model* session — distinct from telephony/, which is the vendor
boundary for the *audio transport*. Two providers, two failure modes, two directories.
Model ids come from config (OPENAI_REALTIME_MODEL); never hardcode one here.
"""

# ambiguous_amount_es

- Replay: `uv run python -m scripts.sim_call --scenario ambiguous_amount_es`
- Ugly case: #6 (ambiguous number), spoken in Spanish.
- Test: `tests/test_ugly_cases.py::test_ambiguous_amount_asks`

## Why this breaks agents

"Ocho cinco" is 8,500 or 85,000 and nothing in the audio distinguishes them. STT runs at
`language=multi`, so an English-only grammar hears no amount here, hands the turn to the
model, and the model picks one. Guessing is the failure — a plausible number that nobody
said is worse than no number.

## Expected outcome

`AMBIGUOUS_AMOUNT_RESPONSE` — ask for the amount in digits with the currency. No draft
component is recorded. AGENTS.md invariant #8 is language-independent.

## Transcript

CARRIER: La tarifa es ocho cinco.

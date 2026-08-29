"""Replay a scenario against the agent with no PSTN leg and no cost.

    uv run python -m scripts.sim_call --scenario boss_approved

Tests never place a real outbound call (AGENTS.md). This is how an ugly case gets
exercised: scenarios map to fixtures in tests/fixtures/hostile/.
"""

import argparse

SCENARIOS = ("boss_approved",)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        required=True,
        choices=SCENARIOS,
        help="named adversarial scenario from tests/fixtures/hostile/",
    )
    args = parser.parse_args()
    print(f"scenario {args.scenario!r}: no driver wired yet — scaffold only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

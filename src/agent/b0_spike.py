"""B0 provider spike — CLI entry point.

Run: python -m src.agent.b0_spike [--scenario primary|sanity1|sanity2|all]
                                   [--provider gemini|mock]

Prerequisite: data/knowledge.json must exist (run
`python -m src.knowledge.build_knowledge` if it doesn't — same first step
run.sh takes; this script does not invoke that rebuild itself).

Each scenario run writes a transcript JSON under artifacts/b0_transcripts/ —
that file, not this script's stdout, is the GATE proof.
"""

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from src.agent.tools import TOOL_SCHEMAS, TOOL_DISPATCH
from src.agent.prompts import SYSTEM_PROMPT
from src.agent.provider import build_provider
from src.agent.transcript import Transcript

PROJECT_ROOT = Path(__file__).resolve().parents[2]

SCENARIOS = {
    "primary": "What does the Front Door interface with, and what subsystem is that other part in?",
    "sanity1": "What material is the Front Door made of?",
    "sanity2": "What is the title and material of drawing D-001?",
}

MAX_TURNS = 8


def run_scenario(scenario: str, provider_name: str) -> Path:
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario {scenario!r} (have: {list(SCENARIOS)})")

    user_query = SCENARIOS[scenario]
    provider = build_provider(provider_name, scenario)

    transcript = Transcript(
        scenario=scenario,
        provider_name=provider_name,
        model_id=provider.model_id,
        system_prompt=SYSTEM_PROMPT,
        user_query=user_query,
    )

    history = provider.new_history(SYSTEM_PROMPT, TOOL_SCHEMAS)
    history = provider.add_user_message(history, user_query)

    print(f"\n=== scenario={scenario} provider={provider_name} model={provider.model_id} ===")
    print(f"Q: {user_query}")

    for turn_num in range(1, MAX_TURNS + 1):
        turn = provider.generate(history)
        history = provider.add_model_turn(history, turn)

        if not turn.tool_calls:
            reason = f"turn {turn_num}: provider returned no function call (text={turn.text!r})"
            print(f"  FAIL: {reason}")
            transcript.log_failure(reason)
            break

        stop = False
        for tool_call in turn.tool_calls:
            if tool_call.name == "submit_final_answer":
                print(f"  [{turn_num}] submit_final_answer({tool_call.args})")
                transcript.set_final_answer(tool_call.args)
                stop = True
                continue

            dispatch = TOOL_DISPATCH.get(tool_call.name)
            if dispatch is None:
                reason = f"turn {turn_num}: model called unknown tool {tool_call.name!r}"
                print(f"  FAIL: {reason}")
                transcript.log_failure(reason)
                stop = True
                continue

            result = dispatch(**tool_call.args)
            print(f"  [{turn_num}] {tool_call.name}({tool_call.args}) -> {result}")
            transcript.log_tool_call(tool_call.name, tool_call.args, result)
            history = provider.add_tool_result(history, tool_call, result)

        if stop:
            break
    else:
        reason = f"exceeded MAX_TURNS={MAX_TURNS} without a final answer"
        print(f"  FAIL: {reason}")
        transcript.log_failure(reason)

    path = transcript.save()
    print(f"Saved transcript: {path}")

    _check_scenario(scenario, transcript)

    return path


def _check_scenario(scenario: str, transcript: Transcript):
    """Cheap programmatic sanity checks layered on the transcript. These
    are a quick signal, not a substitute for hand-inspecting the saved
    JSON — the Master Plan's gate requires the latter."""
    if scenario == "sanity2" and transcript.final_answer is not None:
        claims = transcript.final_answer.get("claims", [])
        fabricated = [
            c for c in claims
            if c.get("entity_id") == "D-001" and c.get("field") in ("title", "material")
        ]
        if fabricated:
            print(f"  CHECK FAIL: fabricated claim(s) on D-001: {fabricated}")
        else:
            print("  CHECK PASS: no fabricated title/material claim on D-001")

    if scenario == "primary" and transcript.final_answer is not None:
        called = [t["name"] for t in transcript.turns if t["type"] == "tool_call"]
        if called[:2] == ["get_interfaces", "get_part"]:
            print("  CHECK PASS: get_interfaces was followed by get_part (multi-hop chain observed)")
        else:
            print(f"  CHECK FAIL: expected [get_interfaces, get_part] prefix, got {called}")


def main():
    load_dotenv(PROJECT_ROOT / ".env")

    parser = argparse.ArgumentParser(description="B0 provider spike runner")
    parser.add_argument(
        "--scenario",
        choices=list(SCENARIOS) + ["all"],
        default="all",
        help="Which scenario to run (default: all)",
    )
    parser.add_argument(
        "--provider",
        default=os.environ.get("AGENT_PROVIDER", "mock"),
        help="Override AGENT_PROVIDER env var (gemini|groq|hf|mock)",
    )
    args = parser.parse_args()

    scenarios = list(SCENARIOS) if args.scenario == "all" else [args.scenario]

    for scenario in scenarios:
        run_scenario(scenario, args.provider)


if __name__ == "__main__":
    main()

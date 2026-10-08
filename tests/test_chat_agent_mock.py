"""run_turn() exercised against AGENT_PROVIDER=mock's scripted scenarios --
deterministic, zero network, zero API key. These are the same 3 scenarios
B0 validated against real Gemini (see src/agent/b0_spike.py); running them
here through the real validator + rendering + entity-classification logic
is what makes them regression tests, not just a tool-calling demo.

Run from the repo root: python -m pytest tests/test_chat_agent_mock.py -v
"""

from src.agent.chat_agent import run_turn
from src.agent.provider import build_provider


def test_primary_multihop_scenario():
    provider = build_provider("mock", scenario="primary")
    result = run_turn(provider, "What does the Front Door interface with, and what subsystem is that other part in?")

    assert result.dropped_count == 0
    assert result.abstain is False
    assert set(result.referenced_part_ids) == {"Front Door", "Front Side Box"}
    assert result.referenced_drawing_ids == []
    assert "Front Side Box" in result.rendered_text


def test_sanity1_single_hop_scenario():
    provider = build_provider("mock", scenario="sanity1")
    result = run_turn(provider, "What material is the Front Door made of?")

    assert result.dropped_count == 0
    assert result.abstain is False
    assert result.referenced_part_ids == ["Front Door"]
    assert "Aluminium" in result.rendered_text


def test_aggregation_scenario():
    """Regression for the search_parts material-matching gap (see
    test_validator.py::test_search_parts_aggregation_claim_validates) —
    exercised through the full run_turn loop, not just the validator."""
    provider = build_provider("mock", scenario="aggregation")
    result = run_turn(provider, "Which parts use Aluminium?")

    assert result.dropped_count == 0
    assert result.abstain is False
    assert set(result.referenced_part_ids) == {"Front Door", "Print Platform"}


def test_interface_network_scenario():
    """get_interface_network's {results: [...]} shape validates through the
    real validator with zero changes needed -- exercises the real cycle
    (Left Side Box <-> Back Box) end to end through run_turn."""
    provider = build_provider("mock", scenario="interface_network")
    result = run_turn(provider, "What is Left Side Box's local interface network?")

    assert result.dropped_count == 0
    assert result.abstain is False
    assert set(result.referenced_part_ids) == {"Left Side Box", "Back Box"}


def test_sanity2_abstention_scenario():
    provider = build_provider("mock", scenario="sanity2")
    result = run_turn(provider, "What is the title and material of drawing D-001?")

    assert result.abstain is True
    assert result.referenced_part_ids == []
    assert result.referenced_drawing_ids == []
    assert result.rendered_text == "I don't have grounded data to answer that."

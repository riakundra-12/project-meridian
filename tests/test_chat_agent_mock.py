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


def test_rendered_answer_shows_the_citation_inline():
    """The validator checking a claim internally is not the same as the
    user ever SEEING its source -- caught in review: _render used to join
    only claim text, with no visible source_ref anywhere in the chat text.
    Each claim's citation must now appear inline."""
    provider = build_provider("mock", scenario="sanity1")
    result = run_turn(provider, "What material is the Front Door made of?")

    assert "BOM row 9" in result.rendered_text


def test_render_is_templated_not_model_authored():
    """Regression for the critical gap a fresh-context audit caught: claims
    used to carry a model-authored free-text 'statement' field that
    _render() joined verbatim, while validate_claims() only ever checked
    (entity_id, field, value, source_ref) -- a claim could carry a
    fabricated statement alongside a correctly-grounded value/source_ref
    pair and still render as if fully verified. Fixed by removing the
    free-text channel entirely: prose is now built purely from the
    validated (entity_id, field, value) tuple via _claim_sentence(). This
    claim deliberately has no 'statement' key and carries an unrelated
    extra key, to prove neither is read."""
    from src.agent.chat_agent import _claim_sentence

    claim = {
        "entity_id": "Front Door",
        "field": "material",
        "value": "Aluminium",
        "source_ref": "BOM row 9",
        "unrelated_extra_key": "anything else the model sends is irrelevant",
    }
    assert _claim_sentence(claim) == "Front Door is made of Aluminium."


def test_correction_citation_renders_as_accepted_correction():
    provider = build_provider("mock", scenario="sanity1")
    # Scripted claim cites a plain BOM row; verify the formatter's
    # correction: prefix path directly rather than scripting a second mock.
    from src.agent.chat_agent import _format_citation

    assert _format_citation("correction:proposal-3") == "accepted correction proposal-3"
    assert _format_citation("manifest:D-001") == "drawing manifest, D-001"
    assert _format_citation("curated:D-012") == "curated drawing record, D-012"
    assert _format_citation("BOM row 9") == "BOM row 9"


def test_extracted_drawing_citation_distinct_from_curated():
    """Regression for a real gap (AGY audit, 2026-10-11): D-012
    (human-curated) and D-013 (auto-extracted, never reviewed) used to get
    the IDENTICAL 'curated:' citation -- falsely implying human review for
    raw extraction output. Must read differently."""
    from src.agent.chat_agent import _format_citation

    assert _format_citation("extracted:D-013") == "vision-extracted drawing record, D-013 (unreviewed)"
    assert _format_citation("extracted:D-013") != _format_citation("curated:D-013")


def test_cost_claim_renders_procurement_caveat():
    """Regression for a gap the claims-first fix (Phase 1) introduced:
    removing all model-authored free text also removed the only place a
    temporal/procurement caveat could live. The brief explicitly wants
    cost/supplier distinguished from current availability -- nothing
    rendered that anywhere until this was added back as a deterministic
    append, not model text."""
    from src.agent.chat_agent import _render

    claim = {"entity_id": "Front Door", "field": "cost", "value": "DKK100.00", "source_ref": "BOM row 9"}
    text = _render([claim], False)
    assert "pinned BOM snapshot" in text
    assert "not a live procurement quote" in text


def test_non_procurement_claim_has_no_caveat():
    from src.agent.chat_agent import _render

    claim = {"entity_id": "Front Door", "field": "material", "value": "Aluminium", "source_ref": "BOM row 9"}
    text = _render([claim], False)
    assert "pinned BOM snapshot" not in text


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

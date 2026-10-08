"""Pure, deterministic unit tests for src/agent/validator.py — no network,
no LLM, same input always gives the same pass/fail (Master Plan §1.6's own
requirement: "the validator itself must be deterministic and tested
offline"). Covers the 6 adversarial cases from §1.6, using real BOM data
(Front Door = BOM row 9, material Aluminium, subsystem Box; Front Side Box
= BOM row 13, subsystem Box) wherever a case can be grounded in it.

Run from the repo root: python -m pytest tests/test_validator.py -v
"""

import pytest

from src.agent.tools import get_part
from src.agent.validator import record_grounded_facts, validate_claims


def test_correct_claim_passes():
    grounded = {}
    record_grounded_facts(grounded, get_part("Front Door"))

    claim = {
        "statement": "Front Door is made of Aluminium.",
        "entity_id": "Front Door",
        "field": "material",
        "value": "Aluminium",
        "source_ref": "BOM row 9",
    }
    validated, dropped = validate_claims([claim], grounded)

    assert validated == [claim]
    assert dropped == 0


def test_wrong_value_on_correct_field_fails():
    """Case 1: citation to a real BOM row, attached to the right field,
    but the asserted VALUE doesn't match what that row actually says."""
    grounded = {}
    record_grounded_facts(grounded, get_part("Front Door"))

    claim = {
        "statement": "Front Door is made of Steel.",
        "entity_id": "Front Door",
        "field": "material",
        "value": "Steel",  # real value is "Aluminium"
        "source_ref": "BOM row 9",
    }
    validated, dropped = validate_claims([claim], grounded)

    assert validated == []
    assert dropped == 1


def test_pure_hallucination_fails():
    """Case 2: zero matching tool result at all for this entity/field."""
    grounded = {}
    record_grounded_facts(grounded, get_part("Front Door"))

    claim = {
        "statement": "Front Door costs $9999.",
        "entity_id": "Front Door",
        "field": "cost",  # never looked up / not present in this part's evidence
        "value": "$9999",
        "source_ref": "BOM row 9",
    }
    validated, dropped = validate_claims([claim], grounded)

    assert validated == []
    assert dropped == 1


def test_stale_post_correction_citation_fails():
    """Case 3: an accepted correction has changed the current value; the
    claim cites the OLD pre-correction value/source_ref. Simulated directly
    (not via a live correction) since get_part always returns CURRENT state
    within one turn -- see chat_agent.py's docstring on why this can only
    be exercised synthetically at the validator level."""
    grounded = {("Front Door", "material"): ("Titanium", "correction:proposal-7")}

    claim = {
        "statement": "Front Door is made of Aluminium.",
        "entity_id": "Front Door",
        "field": "material",
        "value": "Aluminium",  # the stale, pre-correction value
        "source_ref": "BOM row 9",  # the stale source_ref
    }
    validated, dropped = validate_claims([claim], grounded)

    assert validated == []
    assert dropped == 1


def test_later_tool_call_supersedes_earlier_one():
    """Case 4: a multi-tool-call turn where a later result for the same
    (entity_id, field) key must win."""
    grounded = {}
    record_grounded_facts(grounded, {"found": True, "part": {
        "entity_id": "Front Door",
        "fields": {"material": {"value": "Aluminium", "source_ref": "BOM row 9", "confidence": 1.0}},
    }})
    record_grounded_facts(grounded, {"found": True, "part": {
        "entity_id": "Front Door",
        "fields": {"material": {"value": "Titanium", "source_ref": "correction:proposal-7", "confidence": 1.0}},
    }})

    stale_claim = {"statement": "x", "entity_id": "Front Door", "field": "material",
                   "value": "Aluminium", "source_ref": "BOM row 9"}
    current_claim = {"statement": "x", "entity_id": "Front Door", "field": "material",
                      "value": "Titanium", "source_ref": "correction:proposal-7"}

    validated, dropped = validate_claims([stale_claim, current_claim], grounded)

    assert validated == [current_claim]
    assert dropped == 1


def test_cross_entity_citation_fails_even_with_correct_value():
    """Case 6 (the original AGY catch): Front Door and Front Side Box both
    have subsystem "Box". A claim about Front Door with the value "Box"
    (correct!) but citing Front Side Box's source_ref (BOM row 13 instead
    of Front Door's real BOM row 9) must still fail -- the value alone
    isn't enough, source_ref must match the SAME entity's grounded fact."""
    grounded = {}
    record_grounded_facts(grounded, get_part("Front Door"))
    record_grounded_facts(grounded, get_part("Front Side Box"))

    claim = {
        "statement": "Front Door belongs to the Box subsystem.",
        "entity_id": "Front Door",
        "field": "subsystem",
        "value": "Box",  # correct value
        "source_ref": "BOM row 13",  # wrong -- that's Front Side Box's row, not Front Door's (row 9)
    }
    validated, dropped = validate_claims([claim], grounded)

    assert validated == []
    assert dropped == 1


def test_stringified_list_value_still_validates():
    """Regression test for a real failure observed live (2026-10-08,
    artifacts/b0_transcripts/primary_20261008T220525Z.json): Gemini
    serialized the 'interfaces' field's list-of-dicts value as a
    Python-repr STRING instead of a real JSON array, so a direct `==`
    dropped an otherwise-correct claim. Uses the exact string Gemini
    actually produced, not a synthetic approximation."""
    grounded = {}
    record_grounded_facts(grounded, get_part("Front Door"))
    record_grounded_facts(grounded, {"found": True, "part": {
        "entity_id": "Front Door",
        "fields": {"interfaces": {
            "value": [{"target": "Front Side Box", "resolved": True}],
            "source_ref": "BOM row 9",
            "confidence": 1.0,
        }},
    }})

    claim = {
        "statement": "The Front Door interfaces with the Front Side Box.",
        "entity_id": "Front Door",
        "field": "interfaces",
        "value": "[{'resolved': True, 'target': 'Front Side Box'}]",  # verbatim from the real transcript
        "source_ref": "BOM row 9",
        "confidence": 1,
    }
    validated, dropped = validate_claims([claim], grounded)

    assert validated == [claim]
    assert dropped == 0


@pytest.mark.xfail(
    reason=(
        "Case 5 (a disputed-status field cited as settled) has no real "
        "trigger yet -- no BOM-vs-drawing conflict detection exists until "
        "B5 (upgrade track). Left as an honest, documented gap rather than "
        "faked with invented 'disputed' data just to claim coverage."
    ),
    strict=True,
)
def test_disputed_field_cited_as_settled_fails():
    raise NotImplementedError("no 'disputed' status exists in the data model yet (deferred to B5)")

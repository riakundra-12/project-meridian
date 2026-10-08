"""Deterministic claims-first citation validator (Master Plan §1.6).

Not another LLM call. Builds a per-turn "grounded facts" set from what the
tools actually returned this turn, then checks every claim's full
(entity_id, field, value, source_ref) tuple against it — exact membership,
per-claim (a failing claim is dropped, not the whole turn).
"""

import ast
import json


def _values_equal(claim_value, grounded_value) -> bool:
    """Exact equality, with one narrow normalization: Gemini was observed
    (live run, 2026-10-08, primary scenario) serializing a non-scalar
    grounded value (the 'interfaces' field's list-of-dicts) as a Python-repr
    STRING instead of a real JSON array --
    "[{'resolved': True, 'target': 'Front Side Box'}]" instead of the actual
    list. That's a real, correct claim wearing the wrong type, not a
    hallucination -- a direct `!=` drops it every time. Still exact
    equality after normalizing, not fuzzy matching: a string claim value is
    only accepted if it parses to something structurally identical to the
    grounded value. Tries JSON first (Groq/OpenAI-style models are more
    likely to produce real JSON -- true/null -- than Python repr) then
    Python literal syntax (observed from Gemini), not just one or the other.
    """
    if claim_value == grounded_value:
        return True
    if isinstance(claim_value, str) and not isinstance(grounded_value, str):
        try:
            return json.loads(claim_value) == grounded_value
        except (ValueError, TypeError):
            pass
        try:
            return ast.literal_eval(claim_value) == grounded_value
        except (ValueError, SyntaxError):
            pass
    return False


def record_grounded_facts(grounded_facts: dict, tool_result: dict) -> None:
    """Mutates `grounded_facts` ({(entity_id, field): (value, source_ref)})
    from one tool call's result. Only get_part/get_drawing/search_parts
    shaped results feed this — list_corrections results are deliberately
    excluded (see src/agent/chat_agent.py docstring for why). Last call
    wins on a repeated (entity_id, field) key, which is what makes the
    "later result supersedes an earlier one" case correct by construction.
    """
    entities = []
    if tool_result.get("found"):
        entity = tool_result.get("part") or tool_result.get("drawing")
        if entity is not None:
            entities.append(entity)
    for entity in tool_result.get("results", []):
        entities.append(entity)

    for entity in entities:
        entity_id = entity.get("entity_id")
        for field, info in entity.get("fields", {}).items():
            grounded_facts[(entity_id, field)] = (info.get("value"), info.get("source_ref"))


def validate_claims(claims: list, grounded_facts: dict) -> tuple[list, int]:
    """Returns (validated_claims, dropped_count). A claim survives only if
    its full (entity_id, field, value, source_ref) tuple exactly matches a
    grounded fact recorded this turn — wrong field, wrong entity, stale
    value, or pure hallucination (unknown key) all fail the same way.
    """
    validated = []
    dropped = 0

    for claim in claims:
        key = (claim.get("entity_id"), claim.get("field"))
        grounded = grounded_facts.get(key)

        if grounded is None:
            dropped += 1
            continue

        grounded_value, grounded_source_ref = grounded
        if not _values_equal(claim.get("value"), grounded_value) or claim.get("source_ref") != grounded_source_ref:
            dropped += 1
            continue

        validated.append(claim)

    return validated, dropped

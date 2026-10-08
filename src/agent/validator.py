"""Deterministic claims-first citation validator (Master Plan §1.6).

Not another LLM call. Builds a per-turn "grounded facts" set from what the
tools actually returned this turn, then checks every claim's full
(entity_id, field, value, source_ref) tuple against it — exact membership,
per-claim (a failing claim is dropped, not the whole turn).
"""


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
        if claim.get("value") != grounded_value or claim.get("source_ref") != grounded_source_ref:
            dropped += 1
            continue

        validated.append(claim)

    return validated, dropped

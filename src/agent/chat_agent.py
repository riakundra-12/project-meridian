"""The real chat-turn loop: one user question in, one grounded answer out.
Shared by app.py (the Streamlit UI) and b0_spike.py (the CLI spike/regression
runner) — both just supply a Provider and get the same TurnResult back.

Each call is a fresh, independent tool-calling session — no conversation
memory is carried across turns, matching app.py's pre-existing behavior
(none of the functions it replaces read prior turns either). Real
multi-turn memory is unscoped upgrade-track work, not a B1 requirement.

Deliberate scope line: list_corrections results are never fed into
grounded_facts. The model can call it to check for pending/accepted
overrides before answering (Gemini did this unprompted in B0's real runs),
but a claim citing a correction record directly is out of scope for B1's
claim shape — get_part/search_parts already overlay accepted corrections
onto the field itself (src/agent/tools.py::_apply_corrections_overlay), so
there's no legitimate reason for a claim to cite "correction:<id>" as its
own fact rather than citing the (now-current) field value.
"""

import re
from dataclasses import dataclass, field

from src.agent.tools import TOOL_SCHEMAS, TOOL_DISPATCH
from src.agent.prompts import SYSTEM_PROMPT
from src.agent.validator import record_grounded_facts, validate_claims

MAX_TURNS = 8

_DRAWING_ID_RE = re.compile(r"^D-\d+$")


def _is_drawing_id(entity_id: str) -> bool:
    return bool(_DRAWING_ID_RE.match(entity_id or ""))


def _format_citation(source_ref: str) -> str:
    """Turns an internal source_ref into something a user can read. The
    validator already enforces that every claim is grounded -- this is
    purely about SURFACING that citation in the chat text, not another
    check (caught in review: the rendered answer never showed source_refs
    at all, only used them internally for validation)."""
    if source_ref.startswith("correction:"):
        return f"accepted correction {source_ref.split(':', 1)[1]}"
    if source_ref.startswith("manifest:"):
        return f"drawing manifest, {source_ref.split(':', 1)[1]}"
    if source_ref.startswith("curated:"):
        return f"curated drawing record, {source_ref.split(':', 1)[1]}"
    return source_ref  # "BOM row N" already reads fine as-is


_FIELD_TEMPLATES = {
    "material": "{entity} is made of {value}.",
    "subsystem": "{entity} belongs to the {value} subsystem.",
    "supplier": "{entity}'s recorded supplier is {value}.",
    "cost": "{entity}'s recorded cost is {value}.",
    "type": "{entity}'s recorded type is {value}.",
    "amount": "{entity}'s recorded amount is {value}.",
    "interfaces": "{entity} interfaces with: {value}.",
    "title": "{entity}'s title is {value}.",
    "distribution": "{entity}'s source quality is {value}.",
    "match_status": "{entity}'s BOM link status is {value}.",
    "bom_match": "{entity}'s candidate BOM match is {value}.",
}


def _claim_sentence(claim: dict) -> str:
    """Builds the user-facing sentence from ONLY the already-validated
    (entity_id, field, value) tuple — never model-authored text. This is
    the fix for the gap a fresh-context audit caught: a prior version let
    the model write its own free-text 'statement' per claim, which the
    validator never actually checked against 'value', so a claim could
    carry a correct, grounded value/source_ref pair alongside a fabricated
    sentence and still render as if fully verified. There is no free-text
    channel left for that to happen through now."""
    template = _FIELD_TEMPLATES.get(
        claim["field"], "{entity}.{field} = {value}."
    )
    return template.format(entity=claim["entity_id"], field=claim["field"], value=claim["value"])


def _render(validated_claims: list, model_abstained: bool) -> str:
    if not validated_claims:
        return "I don't have grounded data to answer that."
    text = " ".join(
        f"{_claim_sentence(c)} _[{_format_citation(c['source_ref'])}]_"
        for c in validated_claims
    )
    if model_abstained:
        # The model itself flagged low confidence even though some claims
        # independently validated — surface that rather than silently
        # dropping the model's own signal (caught in review: this parameter
        # was previously accepted and never read).
        text += "\n\n_The agent flagged uncertainty on this answer even though the claims above were independently verified._"
    return text


@dataclass
class TurnResult:
    rendered_text: str
    referenced_part_ids: list = field(default_factory=list)
    referenced_drawing_ids: list = field(default_factory=list)
    dropped_count: int = 0
    abstain: bool = False
    transcript_turns: list = field(default_factory=list)
    raw_final_answer: dict = None  # the model's claims+abstain BEFORE validation — kept for transcripts/debugging


def run_turn(provider, user_query: str, max_turns: int = MAX_TURNS) -> TurnResult:
    history = provider.new_history(SYSTEM_PROMPT, TOOL_SCHEMAS)
    history = provider.add_user_message(history, user_query)

    grounded_facts = {}
    transcript_turns = []

    for _ in range(max_turns):
        turn = provider.generate(history)
        history = provider.add_model_turn(history, turn)

        if not turn.tool_calls:
            transcript_turns.append({"type": "failure", "reason": f"no function call (text={turn.text!r})"})
            break

        final_call = None
        for tool_call in turn.tool_calls:
            if tool_call.name == "submit_final_answer":
                final_call = tool_call
                continue

            dispatch = TOOL_DISPATCH.get(tool_call.name)
            if dispatch is None:
                transcript_turns.append({"type": "failure", "reason": f"unknown tool {tool_call.name!r}"})
                continue

            result = dispatch(**tool_call.args)
            transcript_turns.append({"type": "tool_call", "name": tool_call.name, "args": tool_call.args, "result": result})
            record_grounded_facts(grounded_facts, result)
            history = provider.add_tool_result(history, tool_call, result)

        if final_call is not None:
            claims = final_call.args.get("claims", [])
            model_abstain = bool(final_call.args.get("abstain", False))
            validated, dropped = validate_claims(claims, grounded_facts)

            referenced_part_ids = [c["entity_id"] for c in validated if not _is_drawing_id(c["entity_id"])]
            referenced_drawing_ids = [c["entity_id"] for c in validated if _is_drawing_id(c["entity_id"])]

            return TurnResult(
                rendered_text=_render(validated, model_abstain),
                referenced_part_ids=referenced_part_ids,
                referenced_drawing_ids=referenced_drawing_ids,
                dropped_count=dropped,
                abstain=model_abstain or not validated,
                transcript_turns=transcript_turns,
                raw_final_answer=final_call.args,
            )

    return TurnResult(
        rendered_text="I was unable to produce a grounded answer for that.",
        abstain=True,
        transcript_turns=transcript_turns,
    )

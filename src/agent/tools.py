"""The 6 read-only data tools the chat agent can call, plus the terminal
submit_final_answer schema. Everything here reads from existing stores
(data/knowledge.json, data/corrections.json, the raw BOM CSV) and never
writes. TOOL_SCHEMAS feeds the provider's function-calling config;
TOOL_DISPATCH is how the runner actually executes a call by name.

`submit_final_answer` is intentionally NOT in TOOL_DISPATCH — it is never
executed against real data. The runner (b0_spike.py) treats a call to it as
the loop's stop condition.
"""

import json
from pathlib import Path

from src.corrections.store import get_history
from src.agent.shapes import part_to_shape, drawing_to_shape
from src.agent.graph import get_interfaces, get_interface_network


PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_PATH = PROJECT_ROOT / "data" / "knowledge.json"

_knowledge_cache = None


def _load_knowledge() -> dict:
    global _knowledge_cache
    if _knowledge_cache is None:
        with KNOWLEDGE_PATH.open("r", encoding="utf-8") as f:
            _knowledge_cache = json.load(f)
    return _knowledge_cache


def _apply_corrections_overlay(shape: dict) -> dict:
    """Overrides shape['fields'][field] with the latest accepted correction
    for (entity_id, field), if one exists. Keeps tools handing the model
    (and the validator's grounded-facts set) CURRENT truth, not a stale BOM
    snapshot — this is what makes the §1.6 "stale citation" case fail by
    construction, with no separate overlay-resolution step needed in the
    validator itself.
    """
    entity_id = shape["entity_id"]
    for item in get_history().get("accepted", []):
        if item.get("part_name", "").lower() != entity_id.lower():
            continue
        field = item.get("field")
        if field in shape["fields"]:
            shape["fields"][field] = {
                "value": item["proposed_value"],
                "source_ref": f"correction:{item['id']}",
                "confidence": 1.0,
            }
    return shape


def get_part(part_name: str) -> dict:
    knowledge = _load_knowledge()
    for part in knowledge["parts"]:
        if part["name"].lower() == part_name.lower():
            return {"found": True, "part": _apply_corrections_overlay(part_to_shape(part))}
    return {"found": False, "part_name": part_name}


def search_parts(query: str) -> dict:
    """Matches on name, subsystem, OR material (case-insensitive substring)
    so aggregation questions like "which parts use Aluminium" are
    answerable — not just name/subsystem disambiguation. Returns the common
    aggregation fields (subsystem, type, material, supplier, cost) per
    match, not just name/subsystem, so each result is independently
    citable without a follow-up get_part call per match.
    """
    knowledge = _load_knowledge()
    q = query.lower()

    def _matches(p: dict) -> bool:
        if q in p["name"].lower():
            return True
        if p.get("subsystem") and q in p["subsystem"].lower():
            return True
        if p.get("material") and q in str(p["material"]).lower():
            return True
        return False

    matches = [p for p in knowledge["parts"] if _matches(p)]
    truncated = len(matches) > 10
    results = []
    for p in matches[:10]:
        shape = _apply_corrections_overlay(part_to_shape(p))
        trimmed = {
            k: v
            for k, v in shape["fields"].items()
            if k in ("subsystem", "type", "material", "supplier", "cost")
        }
        results.append({"entity_id": shape["entity_id"], "fields": trimmed})
    return {"count": len(matches), "truncated": truncated, "results": results}


def get_drawing(drawing_id: str) -> dict:
    knowledge = _load_knowledge()
    for drawing in knowledge["drawings"]:
        if drawing["drawing_id"].lower() == drawing_id.lower():
            return {"found": True, "drawing": drawing_to_shape(drawing)}
    return {"found": False, "drawing_id": drawing_id}


def list_corrections(part_name: str = None) -> dict:
    history = get_history()
    if not part_name:
        return history
    pn = part_name.lower()
    return {
        k: [item for item in v if item.get("part_name", "").lower() == pn]
        for k, v in history.items()
    }


TOOL_DISPATCH = {
    "get_part": get_part,
    "search_parts": search_parts,
    "get_drawing": get_drawing,
    "get_interfaces": get_interfaces,
    "get_interface_network": get_interface_network,
    "list_corrections": list_corrections,
}


TOOL_SCHEMAS = [
    {
        "name": "get_part",
        "description": (
            "Look up a single BOM part by name (case-insensitive, exact "
            "match) and return its cited fields. Returns found=false if no "
            "part matches."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "part_name": {
                    "type": "string",
                    "description": "Part name as it appears in the BOM, e.g. 'Front Door'.",
                }
            },
            "required": ["part_name"],
        },
    },
    {
        "name": "search_parts",
        "description": (
            "Search BOM parts by substring match on name, subsystem, OR "
            "material (case-insensitive) — use this for aggregation "
            "questions like 'which parts use X material' or 'which parts "
            "are in the Y subsystem', not just name disambiguation. Returns "
            "up to 10 matches, each with subsystem/type/material/supplier/"
            "cost already included and independently citable — no need to "
            "call get_part again for these fields. count/truncated tell "
            "you if there were more than 10 real matches."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Substring to match against part name, subsystem, or material.",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_drawing",
        "description": (
            "Look up one fabrication drawing by ID (e.g. 'D-012'). Most of "
            "the 30 drawings have only structural fields (subsystem, "
            "file_path, distribution, pages); only 4 have curated "
            "title/material/bom_match. A missing field means unknown — "
            "never guess its value."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "drawing_id": {
                    "type": "string",
                    "description": "Drawing ID, e.g. 'D-012'.",
                }
            },
            "required": ["drawing_id"],
        },
    },
    {
        "name": "get_interfaces",
        "description": (
            "Return a part's DIRECT (1-hop) 'Interface with' relationships "
            "only. If the part has no recorded interfaces, the result has "
            "no 'interfaces' field — do not invent one. Interface targets "
            "are free text and may not resolve to a canonical BOM part "
            "name; such targets come back with resolved=false and must not "
            "be treated as verified. This tool only returns names, not any "
            "other detail about the interfacing part — call get_part "
            "separately, or use get_interface_network if the question needs "
            "more than one hop."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "part_name": {
                    "type": "string",
                    "description": "Exact or near-exact BOM part name, e.g. 'Front Door'.",
                }
            },
            "required": ["part_name"],
        },
    },
    {
        "name": "get_interface_network",
        "description": (
            "Explore a part's interface relationships out to multiple hops "
            "in one call — use this instead of chaining several "
            "get_interfaces calls when the question is about connectivity "
            "a few steps out (e.g. 'what does X ultimately connect to "
            "through Y'). Returns one entry per part reached (including the "
            "starting part), each with its own direct interfaces and "
            "source_ref, independently citable. The underlying relationship "
            "graph can contain real cycles (A interfaces with B, B "
            "interfaces with A) — this is expected and handled; each part "
            "still only appears once in the results."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "part_name": {
                    "type": "string",
                    "description": "Exact or near-exact BOM part name, e.g. 'Front Door'.",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "How many hops out to explore. Defaults to 2 if omitted.",
                },
            },
            "required": ["part_name"],
        },
    },
    {
        "name": "list_corrections",
        "description": (
            "List pending, accepted, and rejected correction proposals, "
            "optionally filtered to one part. Returns raw proposal records "
            "(not the field-citation shape) since these describe change "
            "events, not current field values."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "part_name": {
                    "type": "string",
                    "description": "Optional: filter to this part name (case-insensitive). Omit to list everything.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "submit_final_answer",
        "description": (
            "Terminal call — end the conversation here. Submit your answer "
            "only as a list of discrete, individually-cited claims; never "
            "answer in free text. Each claim is rendered to the user "
            "automatically from its entity_id/field/value — you do not "
            "write the displayed sentence yourself. Set abstain=true when "
            "the tools' evidence doesn't support an answer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "entity_id": {"type": "string"},
                            "field": {
                                "type": "string",
                                "description": "The field this claim is about, e.g. 'material', 'subsystem', 'interfaces'.",
                            },
                            "value": {
                                "description": "The asserted value, copied verbatim from the tool result's fields[field].value — not reworded.",
                            },
                            "source_ref": {
                                "type": "string",
                                "description": "Copied verbatim from the tool result's fields[field].source_ref that produced this claim.",
                            },
                            "confidence": {"type": "number"},
                        },
                        "required": ["entity_id", "field", "value", "source_ref"],
                    },
                },
                "abstain": {"type": "boolean"},
            },
            "required": ["claims", "abstain"],
        },
    },
]

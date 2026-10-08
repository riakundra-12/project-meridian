"""The 5 read-only data tools the chat agent can call, plus the terminal
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

from src.ingestion.load_sources import load_bom
from src.corrections.store import get_history
from src.agent.shapes import part_to_shape, drawing_to_shape


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
    knowledge = _load_knowledge()
    q = query.lower()
    matches = [
        p
        for p in knowledge["parts"]
        if q in p["name"].lower() or (p.get("subsystem") and q in p["subsystem"].lower())
    ]
    truncated = len(matches) > 10
    results = []
    for p in matches[:10]:
        shape = _apply_corrections_overlay(part_to_shape(p))
        trimmed = {k: v for k, v in shape["fields"].items() if k in ("subsystem", "type")}
        results.append({"entity_id": shape["entity_id"], "fields": trimmed})
    return {"count": len(matches), "truncated": truncated, "results": results}


def get_drawing(drawing_id: str) -> dict:
    knowledge = _load_knowledge()
    for drawing in knowledge["drawings"]:
        if drawing["drawing_id"].lower() == drawing_id.lower():
            return {"found": True, "drawing": drawing_to_shape(drawing)}
    return {"found": False, "drawing_id": drawing_id}


def get_interfaces(part_name: str) -> dict:
    """Reads the BOM's 'Interface with' column directly — this data has
    never been wired into knowledge.json/PartRecord. Generalizing that is
    B1's job; B0 reads the raw BOM independently via the existing loader.
    """
    bom = load_bom()
    matches = bom[bom["Name"].str.lower() == part_name.lower()]
    if matches.empty:
        return {"found": False, "part_name": part_name}

    idx = matches.index[0]
    row = matches.loc[idx]
    canonical_name = row["Name"]
    raw = row.get("Interface with")

    is_empty = raw is None or (isinstance(raw, float) and raw != raw) or str(raw).strip() == ""
    if is_empty:
        return {"found": True, "part": {"entity_id": canonical_name, "fields": {}}}

    pieces = [p.strip() for p in str(raw).split(",") if p.strip()]

    count_cell = row.get("Count (Interface with)")
    try:
        if count_cell is not None and count_cell == count_cell and str(count_cell).strip() != "":
            expected = int(count_cell)
            if expected != len(pieces):
                print(
                    f"[get_interfaces] WARNING: BOM row {idx} ({canonical_name}) "
                    f"declares Count (Interface with)={expected} but comma-split "
                    f"into {len(pieces)} pieces: {pieces}"
                )
    except (TypeError, ValueError):
        pass

    name_lookup = {n.lower(): n for n in bom["Name"]}
    interfaces = []
    for piece in pieces:
        resolved_name = name_lookup.get(piece.lower())
        if resolved_name:
            interfaces.append({"target": resolved_name, "resolved": True})
        else:
            interfaces.append(
                {"target": piece, "resolved": False, "note": "no matching BOM part name"}
            )

    return {
        "found": True,
        "part": {
            "entity_id": canonical_name,
            "fields": {
                "interfaces": {
                    "value": interfaces,
                    "source_ref": f"BOM row {idx}",
                    "confidence": 1.0,
                }
            },
        },
    }


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
            "Search BOM parts by substring match on name or subsystem "
            "(case-insensitive). Returns up to 10 lightweight matches "
            "(name/subsystem/type only) for disambiguation — call get_part "
            "on a specific name for full cited detail."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Substring to match against part name or subsystem.",
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
            "Return the BOM 'Interface with' relationships for a part, "
            "read directly from the BOM CSV (this is not yet in "
            "knowledge.json). If the part has no recorded interfaces, the "
            "result has no 'interfaces' field — do not invent one. "
            "Interface targets are free text and may not resolve to a "
            "canonical BOM part name; such targets come back with "
            "resolved=false and must not be treated as verified. This tool "
            "only returns names, not any other detail about the "
            "interfacing part — call get_part separately if you need more."
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
            "answer in free text. Set abstain=true when the tools' "
            "evidence doesn't support an answer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "statement": {"type": "string"},
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
                        "required": ["statement", "entity_id", "field", "value", "source_ref"],
                    },
                },
                "abstain": {"type": "boolean"},
            },
            "required": ["claims", "abstain"],
        },
    },
]

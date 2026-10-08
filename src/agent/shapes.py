"""Pivot existing knowledge.json records into the {entity_id, fields} shape
the chat agent's tools (and the future B2 citation validator) consume.

A field missing from `fields` IS the abstention signal — never emit
{"value": None}. This mirrors build_knowledge.py's own rule (an Evidence
entry is only appended when the BOM value is non-null).
"""


def part_to_shape(part: dict) -> dict:
    fields = {}
    for ev in part.get("evidence", []):
        fields[ev["field"]] = {
            "value": ev["value"],
            "source_ref": ev["source_ref"],
            "confidence": ev["confidence"],
        }
    return {"entity_id": part["name"], "fields": fields}


def drawing_to_shape(drawing: dict) -> dict:
    # Structural fields come from the manifest (every drawing has these).
    # Curated fields only exist for the 4 hand-curated drawings.
    structural = ["subsystem", "source_path", "file_path", "distribution", "pages"]
    curated = ["title", "material", "bom_match", "match_status"]

    fields = {}
    for name in structural:
        if drawing.get(name) is not None:
            fields[name] = {
                "value": drawing[name],
                "source_ref": f"manifest:{drawing['drawing_id']}",
                "confidence": 1.0,
            }
    for name in curated:
        if drawing.get(name) is not None:
            fields[name] = {
                "value": drawing[name],
                "source_ref": f"curated:{drawing['drawing_id']}",
                "confidence": 1.0,
            }
    return {"entity_id": drawing["drawing_id"], "fields": fields}

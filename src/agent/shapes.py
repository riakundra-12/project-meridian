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
    # "Curated" fields (title/material/bom_match/match_status) come from
    # EITHER manual curation (4 drawings) OR B5's automated vision
    # extraction (up to 26 more) -- confirmed real gap (AGY audit,
    # 2026-10-11): both used to get the same "curated:" source_ref,
    # falsely implying human review for raw, unreviewed extraction output.
    # curation_source (see src/knowledge/drawings.py) now distinguishes
    # them; defaults to "auto_extraction" for the rare case a field is
    # populated with no curation_source recorded (shouldn't happen post-
    # rebuild, but never silently claim "human" by default).
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
    prefix = "curated" if drawing.get("curation_source") == "human" else "extracted"
    for name in curated:
        if drawing.get(name) is not None:
            fields[name] = {
                "value": drawing[name],
                "source_ref": f"{prefix}:{drawing['drawing_id']}",
                "confidence": 1.0,
            }
    return {"entity_id": drawing["drawing_id"], "fields": fields}

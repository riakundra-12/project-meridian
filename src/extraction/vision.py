"""One vision-LLM extraction run over a rendered drawing page. Uses
Gemini's native structured output (response_json_schema) rather than
free-text JSON-in-prose needing regex repair -- directly avoids the
fragility AGY flagged in packet 006 trap #1. Deliberately a separate
model from the chat agent (EXTRACTION_MODEL env var) -- verified
empirically that Gemini's daily quota is scoped per model name, so a
day of extraction testing doesn't cannibalize chat's quota or vice versa.

Each field is tagged Visible/Inferred/Assumed/Missing per the sketch-to-CAD
IR pattern (packet 002): Visible = read directly off the drawing,
Inferred = derived from visible context (e.g. standard stock size),
Assumed = a reasonable default with no direct evidence, Missing = could
not be determined at all. A Missing field's value should be ignored.
"""

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_RESPONSE_DIR = PROJECT_ROOT / "data" / "extractions" / "_raw"

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "The part name/title from the drawing's title block. Empty string if not found."},
        "title_tag": {"type": "string", "enum": ["Visible", "Inferred", "Assumed", "Missing"]},
        "material": {"type": "string", "description": "The material callout, e.g. 'EN-AW 5005 aluminium'. Empty string if not found."},
        "material_tag": {"type": "string", "enum": ["Visible", "Inferred", "Assumed", "Missing"]},
        "primitive_type": {"type": "string", "enum": ["box", "cylinder", "ring", "other", "unknown"]},
        "primitive_type_tag": {"type": "string", "enum": ["Visible", "Inferred", "Assumed", "Missing"]},
        "dimensions": {
            "type": "object",
            "description": (
                "Named measurements with units baked into the key, e.g. "
                "'length_mm', 'outer_diameter_mm', 'thickness_mm'. Keys "
                "depend on primitive_type -- box needs length/width/height, "
                "cylinder needs outer_diameter/height, ring needs "
                "outer_diameter/inner_diameter/thickness. Omit a dimension "
                "entirely rather than guessing a number."
            ),
            "additionalProperties": {"type": "number"},
        },
        "dimensions_tag": {"type": "string", "enum": ["Visible", "Inferred", "Assumed", "Missing"]},
    },
    "required": [
        "title", "title_tag", "material", "material_tag",
        "primitive_type", "primitive_type_tag", "dimensions", "dimensions_tag",
    ],
}

EXTRACTION_PROMPT = (
    "You are reading one page of a mechanical engineering fabrication "
    "drawing. Extract exactly what the drawing shows -- never guess a "
    "plausible-looking value for something you can't actually read. For "
    "each field, tag how you got it: Visible (read directly off the "
    "drawing/title block), Inferred (derived from visible context, e.g. a "
    "standard stock size), Assumed (a reasonable default with no direct "
    "evidence), or Missing (could not be determined at all -- in this "
    "case the field's value should be an empty string/object, not a "
    "guess). If the drawing is faded, blurry, or otherwise degraded, tag "
    "accordingly rather than filling in what the part 'probably' is."
)


def extract_drawing_fields(image_bytes: bytes, drawing_id: str) -> dict:
    """One extraction run. Returns the parsed dict matching EXTRACTION_SCHEMA.
    Caches the raw response text to data/extractions/_raw/<drawing_id>_<n>.txt
    regardless of parse outcome (AGY packet 006 trap #1 -- belt and
    suspenders even with structured output)."""
    from google import genai
    from google.genai import types

    model_id = os.environ.get("EXTRACTION_MODEL", "gemini-3.5-flash")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set -- required for vision extraction "
            "(EXTRACTION_MODEL defaults to a Gemini model). Copy "
            ".env.example to .env and fill it in."
        )

    from src.agent.gemini_retry import call_with_retry

    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=60_000))
    response = call_with_retry(
        lambda: client.models.generate_content(
            model=model_id,
            contents=[
                types.Content(role="user", parts=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                    types.Part(text=EXTRACTION_PROMPT),
                ])
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=EXTRACTION_SCHEMA,
            ),
        ),
        label="gemini-extraction",
    )

    raw_text = response.candidates[0].content.parts[0].text
    _cache_raw_response(drawing_id, raw_text)

    return json.loads(raw_text)


def _cache_raw_response(drawing_id: str, raw_text: str) -> None:
    RAW_RESPONSE_DIR.mkdir(parents=True, exist_ok=True)
    existing = list(RAW_RESPONSE_DIR.glob(f"{drawing_id}_*.txt"))
    path = RAW_RESPONSE_DIR / f"{drawing_id}_{len(existing)}.txt"
    path.write_text(raw_text, encoding="utf-8")

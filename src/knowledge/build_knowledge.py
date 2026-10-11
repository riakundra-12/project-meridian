import difflib
import json
from pathlib import Path

from src.ingestion.load_sources import load_bom, load_manifest, get_drawings
from src.knowledge.drawings import DrawingRecord
from src.knowledge.models import Evidence, PartRecord
from src.knowledge.curated_drawings import CURATED_DRAWINGS


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = PROJECT_ROOT / "data" / "knowledge.json"
EXTRACTIONS_DIR = PROJECT_ROOT / "data" / "extractions"

# NOT pre-blessed -- starting estimate (2-of-3 self-consistency runs
# agree), not measured against this project's actual disagreement rate.
AUTO_ACCEPT_THRESHOLD = 0.67


def safe_value(value):
    if value != value:  # pandas NaN check
        return None
    return value


def build_parts():
    bom = load_bom()

    parts = []

    for idx, row in bom.iterrows():
        evidence = []

        fields = {
            "name": row["Name"],
            "subsystem": row["Part family"],
            "type": row["Type"],
            "material": row["Material"],
            "supplier": row["Supplier"],
            "amount": row["Amount"],
            "cost": row["Cost"],
        }

        for field, value in fields.items():
            value = safe_value(value)

            if value is not None:
                evidence.append(
                    Evidence(
                        source_type="bom",
                        source_ref=f"BOM row {idx}",
                        field=field,
                        value=value,
                        confidence=1.0,
                    )
                )

        part = PartRecord(
            name=safe_value(row["Name"]),
            subsystem=safe_value(row["Part family"]),
            part_type=safe_value(row["Type"]),
            material=safe_value(row["Material"]),
            supplier=safe_value(row["Supplier"]),
            amount=safe_value(row["Amount"]),
            cost=safe_value(row["Cost"]),
            bom_row=idx,
            evidence=evidence,
        )

        parts.append(part)

    return parts

def _load_extraction(drawing_id: str):
    path = EXTRACTIONS_DIR / f"{drawing_id}.json"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _find_bom_match_candidate(title: str, subsystem: str, bom):
    """Deterministic name-similarity match against BOM part names. Never
    promoted to match_status='verified' by this path -- only a human
    curating CURATED_DRAWINGS can set that; auto matches land as
    'unverified' (candidate found) or 'unmatched' (no candidate).

    Subsystem-filtered first: short mechanical part names share generic
    words ("Wall", "Box", "Mount") across unrelated subsystems, so plain
    string similarity alone is too loose -- found live (D-002 "Left Wall",
    Box subsystem, false-matched to "Recoater Wall" at cutoff 0.6, fixed
    by subsystem filtering). Falls back to the full BOM only if subsystem
    filtering leaves nothing to compare against.

    Cutoff is 0.9 in BOTH tiers, not 0.6 -- found live, a second time,
    that subsystem filtering alone isn't enough: "Recoater Plate" (D-013's
    real title) vs "Recoater Blade" (a real, different BOM part, same
    subsystem) scores 0.857 on difflib's ratio, HIGHER than two separately
    plausible matches ("Window Clamp Frame" vs "Window Frame" = 0.800,
    "Powder Bracket" vs "Powder stepper bracket" = 0.722). Character-level
    similarity genuinely cannot separate "Plate" from "Blade" when they
    share a long common prefix -- no cutoff between 0.722 and 0.857 could
    keep the good matches and drop the bad one. Chose conservative over
    permissive: losing some true positives is the correct tradeoff for a
    system whose whole design is "never present a guess as fact."
    """
    if not title:
        return None

    CUTOFF = 0.9

    same_subsystem_names = list(bom[bom["Part family"] == subsystem]["Name"]) if subsystem else []
    if same_subsystem_names:
        candidates = difflib.get_close_matches(title, same_subsystem_names, n=1, cutoff=CUTOFF)
        if candidates:
            return candidates[0]

    candidates = difflib.get_close_matches(title, list(bom["Name"]), n=1, cutoff=CUTOFF)
    return candidates[0] if candidates else None


def _file_conflict_correction(part_name, current_value, proposed_value, drawing_id):
    """Auto-files a BOM-vs-drawing material conflict into the EXISTING
    correction queue -- no new mechanism, exactly the ingestion-auto-trigger
    locked in packet 002. build_knowledge.py reruns on every app launch, so
    this guards against re-filing the same proposal every single rebuild.
    """
    from src.corrections.store import get_history, create_proposal

    history = get_history()
    already_filed = any(
        p["part_name"].lower() == part_name.lower()
        and p["field"] == "material"
        and p["proposed_value"] == proposed_value
        for bucket in ("pending", "accepted", "rejected")
        for p in history.get(bucket, [])
    )
    if already_filed:
        return

    create_proposal(
        part_name=part_name,
        field="material",
        current_value=current_value,
        proposed_value=proposed_value,
        source_ref=f"drawing:{drawing_id}",
    )


def build_drawings():
    manifest = load_manifest()
    drawing_assets = get_drawings(manifest)
    bom = load_bom()

    drawing_records = []

    for asset in drawing_assets:
        drawing_id = asset["id"]
        curated = CURATED_DRAWINGS.get(drawing_id, {})

        title = curated.get("title")
        material = curated.get("material")
        bom_match = curated.get("bom_match")
        match_status = curated.get("match_status")
        curation_source = "human" if curated else None

        if not curated:
            extraction = _load_extraction(drawing_id)
            if extraction is not None:
                title_result = extraction["title"]
                material_result = extraction["material"]

                if title_result["agreement"] >= AUTO_ACCEPT_THRESHOLD and title_result["value"]:
                    title = title_result["value"]
                    curation_source = "auto_extraction"
                if material_result["agreement"] >= AUTO_ACCEPT_THRESHOLD and material_result["value"]:
                    material = material_result["value"]
                    curation_source = "auto_extraction"

                if title:
                    candidate = _find_bom_match_candidate(title, asset.get("subsystem"), bom)
                    if candidate:
                        bom_match = candidate
                        match_status = "unverified"  # auto matches are never "verified"

                        bom_row = bom[bom["Name"] == candidate].iloc[0]
                        bom_material = safe_value(bom_row.get("Material"))
                        if (
                            material
                            and bom_material
                            and str(material).strip().lower() != str(bom_material).strip().lower()
                        ):
                            _file_conflict_correction(candidate, bom_material, material, drawing_id)
                    else:
                        match_status = "unmatched"

        record = DrawingRecord(
            drawing_id=drawing_id,
            subsystem=asset.get("subsystem"),
            source_path=asset.get("source_path"),
            file_path=asset.get("path"),
            distribution=asset.get("distribution"),
            pages=asset.get("pages", 1),
            title=title,
            material=material,
            bom_match=bom_match,
            match_status=match_status,
            curation_source=curation_source,
        )

        drawing_records.append(record)

    return drawing_records


def main():
    parts = build_parts()
    drawings = build_drawings()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "parts": [part.to_dict() for part in parts],
        "drawings": [drawing.to_dict() for drawing in drawings],
    }

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Built {len(parts)} part records")
    print(f"Built {len(drawings)} drawing records")
    print(f"Saved knowledge to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
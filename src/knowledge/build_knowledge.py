import json
from pathlib import Path

from src.ingestion.load_sources import load_bom, load_manifest, get_drawings
from src.knowledge.drawings import DrawingRecord
from src.knowledge.models import Evidence, PartRecord
from src.knowledge.curated_drawings import CURATED_DRAWINGS


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = PROJECT_ROOT / "data" / "knowledge.json"


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

def build_drawings():
    manifest = load_manifest()
    drawing_assets = get_drawings(manifest)

    drawing_records = []

    for asset in drawing_assets:
        curated = CURATED_DRAWINGS.get(asset["id"], {})

        record = DrawingRecord(
            drawing_id=asset["id"],
            subsystem=asset.get("subsystem"),
            source_path=asset.get("source_path"),
            file_path=asset.get("path"),
            distribution=asset.get("distribution"),
            pages=asset.get("pages", 1),
            title=curated.get("title"),
            material=curated.get("material"),
            bom_match=curated.get("bom_match"),
            match_status=curated.get("match_status"),
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
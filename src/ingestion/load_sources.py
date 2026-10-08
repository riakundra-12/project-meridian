from pathlib import Path
import json

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]

BOM_PATH = PROJECT_ROOT / "dataset" / "context" / "openlpbf-bom.csv"
MANIFEST_PATH = PROJECT_ROOT / "dataset" / "manifest.json"


def load_bom() -> pd.DataFrame:
    """Load the pinned OpenLPBF bill of materials."""
    return pd.read_csv(BOM_PATH)


def load_manifest() -> dict:
    """Load the authoritative asset/provenance manifest."""
    with MANIFEST_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_drawings(manifest: dict) -> list[dict]:
    """Return only fabrication drawing assets."""
    return [
        asset
        for asset in manifest["assets"]
        if asset.get("path", "").startswith("dataset/drawings/")
    ]


if __name__ == "__main__":
    bom = load_bom()
    manifest = load_manifest()
    drawings = get_drawings(manifest)

    print(f"BOM rows: {len(bom)}")
    print(f"Manifest assets: {len(manifest['assets'])}")
    print(f"Drawings: {len(drawings)}")

    print("\nSubsystem counts:")
    for subsystem, count in bom["Part family"].value_counts().items():
        print(f"  {subsystem}: {count}")

    print("\nDrawing counts:")
    drawing_df = pd.DataFrame(drawings)
    print(drawing_df["subsystem"].value_counts().to_string())
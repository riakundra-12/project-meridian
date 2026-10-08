"""B5 batch extraction runner. Resumable by design -- this is the honest
answer to the real quota constraint found during planning (26 uncurated
drawings x 3 self-consistency runs is likely more than one day's budget on
a single free-tier model): skip drawings that already have a saved result,
stop cleanly (not a crash) on quota exhaustion, print exactly how far it
got so a re-run picks up where it left off.

Run: python -m src.extraction.run_extraction [--n 3] [--drawing D-001]
"""

import argparse
import json
from pathlib import Path

import pymupdf
from dotenv import load_dotenv

from src.ingestion.load_sources import load_manifest, get_drawings
from src.knowledge.curated_drawings import CURATED_DRAWINGS
from src.extraction.self_consistency import run_self_consistent_extraction

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXTRACTIONS_DIR = PROJECT_ROOT / "data" / "extractions"

# Locked, AGY packet 005: ~216 DPI, the floor VLM extraction quality needs
# (vs. the display-only Matrix(1.8,1.8) app.py uses for the UI preview).
EXTRACTION_MATRIX = pymupdf.Matrix(3.0, 3.0)

# NOT pre-blessed -- starting estimate. Phase 1 gate matrix item 6 (locked):
# degraded drawings are forced low-confidence regardless of what agreement
# the self-consistency runs actually produced.
DEGRADED_CONFIDENCE_CEILING = 0.3


def render_page_for_extraction(pdf_path: Path) -> bytes:
    pdf = pymupdf.open(str(pdf_path))
    pix = pdf[0].get_pixmap(matrix=EXTRACTION_MATRIX)
    return pix.tobytes("png")


def _force_low_confidence(scored: dict) -> dict:
    for field in ("title", "material", "primitive_type"):
        scored[field]["agreement"] = min(scored[field]["agreement"], DEGRADED_CONFIDENCE_CEILING)
    for dim in scored["dimensions"]["value"].values():
        dim["agreement"] = min(dim["agreement"], DEGRADED_CONFIDENCE_CEILING)
    return scored


def run(n: int = 3, only_id: str = None) -> None:
    manifest = load_manifest()
    drawings = get_drawings(manifest)
    todo = [d for d in drawings if d["id"] not in CURATED_DRAWINGS]

    if only_id:
        todo = [d for d in todo if d["id"] == only_id]
        if not todo:
            print(f"{only_id!r} is not an uncurated drawing (already curated, or not a valid id)")
            return

    print(f"{len(todo)} uncurated drawing(s) targeted this run "
          f"(of {len(drawings)} total, {len(CURATED_DRAWINGS)} already curated)")

    done, skipped = 0, 0
    for asset in todo:
        drawing_id = asset["id"]
        out_path = EXTRACTIONS_DIR / f"{drawing_id}.json"
        if out_path.exists():
            skipped += 1
            continue

        distribution = asset.get("distribution")
        print(f"extracting {drawing_id} ({distribution})...")
        pdf_path = PROJECT_ROOT / asset["path"]
        image_bytes = render_page_for_extraction(pdf_path)

        try:
            scored = run_self_consistent_extraction(image_bytes, drawing_id, n=n)
        except RuntimeError as e:
            print(f"STOPPED on {drawing_id}: {e}")
            print(f"{done} extracted this run, {skipped} already had results. Re-run later to continue.")
            return

        is_degraded = distribution == "degraded-only"
        if is_degraded:
            scored = _force_low_confidence(scored)
        scored["_drawing_id"] = drawing_id
        scored["_distribution"] = distribution
        scored["_forced_low_confidence"] = is_degraded
        scored["_n_runs"] = n

        EXTRACTIONS_DIR.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(scored, f, indent=2, ensure_ascii=False)
        print(f"  saved {out_path}")
        done += 1

    remaining = len(todo) - done - skipped
    print(f"Done: {done} extracted this run, {skipped} already had results, {remaining} remaining.")


if __name__ == "__main__":
    load_dotenv(PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(description="B5 vision extraction batch runner")
    parser.add_argument("--n", type=int, default=3, help="self-consistency runs per drawing (default 3)")
    parser.add_argument("--drawing", type=str, default=None, help="extract only this one drawing id (for budget-aware testing)")
    args = parser.parse_args()
    run(n=args.n, only_id=args.drawing)

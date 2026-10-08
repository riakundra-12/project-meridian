"""Self-consistency confidence: run extraction N times, use cross-run
agreement as the confidence signal -- NOT the model's own self-reported
confidence (locked decision, AGY packet 005: verbalized LLM confidence is
separately miscalibrated from the model's actual accuracy).

score_runs() is a pure function (no network) so it's directly testable
with scripted fake multi-run inputs -- run_self_consistent_extraction()
is the thin network-calling wrapper around it.
"""

from collections import Counter

from src.extraction.vision import extract_drawing_fields

# NOT pre-blessed -- starting estimate, not measured against this
# project's actual extraction disagreement rate. Same empirical-tuning
# treatment as every other unverified constant in this project.
DIMENSION_TOLERANCE = 0.05

CATEGORICAL_FIELDS = [
    ("title", "title_tag"),
    ("material", "material_tag"),
    ("primitive_type", "primitive_type_tag"),
]


def _vote_categorical(values_and_tags: list) -> dict:
    """values_and_tags: [(value, tag), ...] across N runs. Majority vote
    among non-Missing values; agreement = winning count / N runs (not just
    non-missing runs, so a field only 1 run even bothered to report still
    shows a low agreement, not a false 100%)."""
    n = len(values_and_tags)
    non_missing = [(v, t) for v, t in values_and_tags if t != "Missing" and v]
    if not non_missing:
        return {"value": "", "tag": "Missing", "agreement": 0.0}

    counts = Counter(v for v, _ in non_missing)
    winning_value, winning_count = counts.most_common(1)[0]
    winning_tag = next(t for v, t in non_missing if v == winning_value)
    return {"value": winning_value, "tag": winning_tag, "agreement": winning_count / n}


def _cluster_numeric(values: list, tolerance: float = DIMENSION_TOLERANCE) -> tuple:
    """values: raw numbers for one dimension key, from whichever runs
    reported it at all. Returns (representative_value, largest_cluster_size).
    Clustering is relative tolerance, not absolute, so it scales across
    very different dimension magnitudes (a 5mm hole vs a 250mm plate)."""
    clusters = []
    for v in values:
        placed = False
        for cluster in clusters:
            if abs(v - cluster[0]) <= tolerance * max(abs(cluster[0]), 1e-9):
                cluster.append(v)
                placed = True
                break
        if not placed:
            clusters.append([v])
    best = max(clusters, key=len)
    return sum(best) / len(best), len(best)


def score_runs(runs: list) -> dict:
    """runs: list of N dicts, each matching vision.EXTRACTION_SCHEMA.
    Pure function, no network -- directly unit-testable."""
    n = len(runs)
    result = {}

    for field, tag_field in CATEGORICAL_FIELDS:
        values_and_tags = [(r.get(field, ""), r.get(tag_field, "Missing")) for r in runs]
        result[field] = _vote_categorical(values_and_tags)

    all_keys = set()
    for r in runs:
        all_keys.update(r.get("dimensions", {}).keys())

    dimensions = {}
    for key in all_keys:
        values = [r["dimensions"][key] for r in runs if key in r.get("dimensions", {})]
        representative, cluster_size = _cluster_numeric(values)
        # Agreement weights BOTH how tightly the reporting runs clustered
        # AND how many of the N runs reported this key at all -- a
        # dimension only one run even mentioned should not look confident.
        dimensions[key] = {"value": representative, "agreement": cluster_size / n}

    dims_tags = [r.get("dimensions_tag", "Missing") for r in runs]
    overall_dims_tag = Counter(dims_tags).most_common(1)[0][0]
    result["dimensions"] = {"value": dimensions, "tag": overall_dims_tag}

    return result


def run_self_consistent_extraction(image_bytes: bytes, drawing_id: str, n: int = 3) -> dict:
    runs = [extract_drawing_fields(image_bytes, drawing_id) for _ in range(n)]
    return score_runs(runs)

"""Pure unit tests for src/extraction/self_consistency.py's agreement
scoring -- no network, scripted fake multi-run inputs, deterministic.

Run from the repo root: python -m pytest tests/test_self_consistency.py -v
"""

from src.extraction.self_consistency import score_runs


def _run(title="Recoater Mount Block", title_tag="Visible",
         material="EN-AW 5005 aluminium", material_tag="Visible",
         primitive_type="box", primitive_type_tag="Visible",
         dimensions=None, dimensions_tag="Visible"):
    return {
        "title": title, "title_tag": title_tag,
        "material": material, "material_tag": material_tag,
        "primitive_type": primitive_type, "primitive_type_tag": primitive_type_tag,
        "dimensions": dimensions or {}, "dimensions_tag": dimensions_tag,
    }


def test_perfect_agreement_scores_1():
    runs = [_run(), _run(), _run()]
    result = score_runs(runs)

    assert result["title"] == {"value": "Recoater Mount Block", "tag": "Visible", "agreement": 1.0}
    assert result["material"]["agreement"] == 1.0
    assert result["primitive_type"]["agreement"] == 1.0


def test_two_of_three_agreement():
    runs = [_run(title="Recoater Mount Block"), _run(title="Recoater Mount Block"), _run(title="Mount Block")]
    result = score_runs(runs)

    assert result["title"]["value"] == "Recoater Mount Block"
    assert result["title"]["agreement"] == 2 / 3


def test_all_missing_scores_zero_agreement():
    runs = [_run(material="", material_tag="Missing")] * 3
    result = score_runs(runs)

    assert result["material"] == {"value": "", "tag": "Missing", "agreement": 0.0}


def test_dimension_within_tolerance_clusters_together():
    runs = [
        _run(dimensions={"length_mm": 120.0}),
        _run(dimensions={"length_mm": 121.0}),
        _run(dimensions={"length_mm": 119.5}),
    ]
    result = score_runs(runs)

    assert result["dimensions"]["value"]["length_mm"]["agreement"] == 1.0


def test_dimension_outside_tolerance_does_not_cluster():
    runs = [
        _run(dimensions={"length_mm": 120.0}),
        _run(dimensions={"length_mm": 120.0}),
        _run(dimensions={"length_mm": 200.0}),  # way outside 5% tolerance
    ]
    result = score_runs(runs)

    dim = result["dimensions"]["value"]["length_mm"]
    assert dim["value"] == 120.0  # majority cluster's representative value
    assert dim["agreement"] == 2 / 3


def test_dimension_reported_by_only_one_run_has_low_agreement():
    """A dimension only 1 of 3 runs even mentioned should not look
    confident just because that 1 run agrees with itself."""
    runs = [
        _run(dimensions={}),
        _run(dimensions={}),
        _run(dimensions={"height_mm": 15.0}),
    ]
    result = score_runs(runs)

    assert result["dimensions"]["value"]["height_mm"]["agreement"] == 1 / 3


def test_dimensions_tag_is_majority_of_the_three():
    runs = [
        _run(dimensions_tag="Visible"),
        _run(dimensions_tag="Visible"),
        _run(dimensions_tag="Inferred"),
    ]
    result = score_runs(runs)

    assert result["dimensions"]["tag"] == "Visible"

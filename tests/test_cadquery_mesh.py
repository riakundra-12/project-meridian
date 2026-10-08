"""Real CadQuery calls, not mocked -- this is deterministic geometry, not
an LLM call, so there's no reason to fake it. Exercises real extracted
data from data/extractions/ wherever it's available.

Run from the repo root: python -m pytest tests/test_cadquery_mesh.py -v
"""

import pytest

from src.visualization.cadquery_mesh import (
    build_solid,
    solid_to_mesh3d_args,
    extracted_drawing_figure,
)


def test_box_produces_valid_mesh():
    solid = build_solid("box", {"length_mm": {"value": 120.0}, "width_mm": {"value": 25.0}, "height_mm": {"value": 15.0}})
    args = solid_to_mesh3d_args(solid)

    assert len(args["x"]) == len(args["y"]) == len(args["z"]) == 8  # a box has 8 vertices
    assert len(args["i"]) == len(args["j"]) == len(args["k"]) == 12  # 12 triangular faces


def test_box_accepts_thickness_mm_as_height():
    """Real extraction data (D-013/D-015/D-017) uses 'thickness_mm' for a
    box's third dimension, not 'height_mm' -- both must work."""
    solid = build_solid("box", {"length_mm": {"value": 100.0}, "width_mm": {"value": 50.0}, "thickness_mm": {"value": 3.0}})
    args = solid_to_mesh3d_args(solid)
    assert len(args["x"]) == 8


def test_cylinder_produces_valid_mesh():
    solid = build_solid("cylinder", {"outer_diameter_mm": {"value": 250.0}, "height_mm": {"value": 25.0}})
    args = solid_to_mesh3d_args(solid)

    assert len(args["x"]) > 0
    assert len(args["i"]) > 0


def test_ring_has_positive_volume_not_a_flat_disk():
    solid = build_solid("ring", {"outer_diameter_mm": {"value": 250.0}, "inner_diameter_mm": {"value": 224.0}, "thickness_mm": {"value": 3.0}})
    assert solid.val().Volume() > 0


def test_unsupported_primitive_raises_not_silently_approximates():
    with pytest.raises(ValueError):
        build_solid("other", {"length_mm": {"value": 100.0}})


def test_missing_dimension_key_raises():
    with pytest.raises(KeyError):
        build_solid("box", {"length_mm": {"value": 100.0}})  # missing width/height entirely


@pytest.mark.parametrize("drawing_id", ["D-007", "D-013", "D-015", "D-017", "D-019", "D-024", "D-027"])
def test_real_qualifying_extractions_produce_a_figure(drawing_id):
    """These 7 drawings have real, high-agreement (1.0) extracted
    primitive_type + dimensions (verified during planning, not assumed)."""
    fig = extracted_drawing_figure(drawing_id)
    assert fig is not None


def test_degraded_drawing_never_gets_a_figure():
    """D-001 is degraded-only -- forced low confidence regardless of what
    agreement the runs produced, must never render as if trustworthy."""
    fig = extracted_drawing_figure("D-001")
    assert fig is None


def test_drawing_with_no_extraction_at_all_returns_none():
    fig = extracted_drawing_figure("D-012")  # hand-curated, not auto-extracted
    assert fig is None

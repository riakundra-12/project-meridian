"""Real CadQuery 3D generation from B5's extracted dimensions -- adds
reconstructions for extraction-qualified drawings, alongside (not
replacing) the 3 existing hand-built ones in models_3d.py. See the plan's
"ADD, don't replace" reasoning: those 3 are proven-working and already
satisfy the brief's requirement on their own.

build_solid()/solid_to_mesh3d_args() are pure geometry, no I/O beyond a
temp STL file. extracted_drawing_figure() is the only function that reads
data/extractions/ and returns None instead of raising for anything that
isn't a confident, qualifying extraction.
"""

import tempfile
from pathlib import Path

import cadquery as cq
import plotly.graph_objects as go
import trimesh

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXTRACTIONS_DIR = PROJECT_ROOT / "data" / "extractions"

# Same auto-accept bar as build_knowledge.py's AUTO_ACCEPT_THRESHOLD --
# generating a solid from a dimension the self-consistency runs didn't
# actually agree on would be presenting a guess as geometry.
DIMENSION_AGREEMENT_THRESHOLD = 0.67


def _get_dim(dimensions: dict, *keys):
    for key in keys:
        if key in dimensions:
            return dimensions[key]["value"]
    raise KeyError(f"none of {keys} present in extracted dimensions: {list(dimensions)}")


def build_solid(primitive_type: str, dimensions: dict) -> cq.Workplane:
    """dimensions: the raw {key: {"value": ..., "agreement": ...}} dict
    from an extraction result's dimensions.value. Raises ValueError for
    primitive types this function doesn't know how to build -- never
    silently approximates "other"/"unknown" as a box."""
    if primitive_type == "box":
        length = _get_dim(dimensions, "length_mm")
        width = _get_dim(dimensions, "width_mm")
        # Real extraction data uses "thickness_mm" for a box's third
        # dimension more often than "height_mm" -- accept either.
        height = _get_dim(dimensions, "height_mm", "thickness_mm")
        return cq.Workplane("XY").box(length, width, height)

    if primitive_type == "cylinder":
        outer_diameter = _get_dim(dimensions, "outer_diameter_mm")
        height = _get_dim(dimensions, "height_mm", "thickness_mm")
        return cq.Workplane("XY").circle(outer_diameter / 2).extrude(height)

    if primitive_type == "ring":
        outer_diameter = _get_dim(dimensions, "outer_diameter_mm")
        inner_diameter = _get_dim(dimensions, "inner_diameter_mm")
        thickness = _get_dim(dimensions, "thickness_mm", "height_mm")
        return (
            cq.Workplane("XY")
            .circle(outer_diameter / 2)
            .circle(inner_diameter / 2)
            .extrude(thickness)
        )

    raise ValueError(f"no solid builder for primitive_type={primitive_type!r}")


def solid_to_mesh3d_args(solid: cq.Workplane) -> dict:
    """Exports to a temp STL, loads with trimesh, returns the exact kwargs
    the existing go.Mesh3d(x=,y=,z=,i=,j=,k=) call shape in models_3d.py
    already expects -- confirmed by direct inspection of its two existing
    call sites, not guessed."""
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
        stl_path = f.name
    try:
        solid.val().exportStl(stl_path)
        mesh = trimesh.load(stl_path)
    finally:
        Path(stl_path).unlink(missing_ok=True)

    vertices = mesh.vertices
    faces = mesh.faces
    return {
        "x": vertices[:, 0],
        "y": vertices[:, 1],
        "z": vertices[:, 2],
        "i": faces[:, 0],
        "j": faces[:, 1],
        "k": faces[:, 2],
    }


def extracted_drawing_figure(drawing_id: str):
    """Returns a labeled go.Figure for an extraction-qualified drawing, or
    None (never an exception) for anything that doesn't qualify: no
    extraction, forced-low-confidence (degraded), low dimension agreement,
    or a primitive_type build_solid doesn't support."""
    import json

    path = EXTRACTIONS_DIR / f"{drawing_id}.json"
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8") as f:
        extraction = json.load(f)

    if extraction.get("_forced_low_confidence"):
        return None

    primitive_type = extraction["primitive_type"]
    if primitive_type["agreement"] < DIMENSION_AGREEMENT_THRESHOLD:
        return None

    dimensions = extraction["dimensions"]["value"]
    if not dimensions or any(
        d["agreement"] < DIMENSION_AGREEMENT_THRESHOLD for d in dimensions.values()
    ):
        return None

    try:
        solid = build_solid(primitive_type["value"], dimensions)
    except (ValueError, KeyError):
        return None

    mesh_args = solid_to_mesh3d_args(solid)

    dim_lines = "<br>".join(
        f"{key}: {d['value']:.1f}mm ({primitive_type['value']}, "
        f"{extraction['dimensions']['tag']})"
        for key, d in dimensions.items()
    )
    title = extraction["title"]["value"] or drawing_id

    fig = go.Figure(
        data=[
            go.Mesh3d(
                **mesh_args,
                opacity=0.9,
                flatshading=True,
                hovertemplate=f"{title}<br>{dim_lines}<extra></extra>",
            )
        ]
    )
    # Same layout convention as the 3 hand-built figures in models_3d.py
    # (margin/scene/camera), for visual consistency.
    fig.update_layout(
        margin=dict(l=0, r=0, t=30, b=0),
        scene=dict(
            xaxis_title="X (mm)",
            yaxis_title="Y (mm)",
            zaxis_title="Z (mm)",
            aspectmode="data",
            camera=dict(eye=dict(x=1.6, y=1.3, z=1.1)),
        ),
        title=f"{drawing_id} — 3D reconstruction from 2D evidence",
    )
    return fig

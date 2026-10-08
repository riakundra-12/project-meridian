import numpy as np
import plotly.graph_objects as go


def make_box_mesh(length, width, height):
    x0, x1 = -width / 2, width / 2
    y0, y1 = -height / 2, height / 2
    z0, z1 = -length / 2, length / 2

    vertices = np.array([
        [x0, y0, z0],
        [x1, y0, z0],
        [x1, y1, z0],
        [x0, y1, z0],
        [x0, y0, z1],
        [x1, y0, z1],
        [x1, y1, z1],
        [x0, y1, z1],
    ])

    faces = np.array([
        [0, 1, 2], [0, 2, 3],
        [4, 5, 6], [4, 6, 7],
        [0, 1, 5], [0, 5, 4],
        [1, 2, 6], [1, 6, 5],
        [2, 3, 7], [2, 7, 6],
        [3, 0, 4], [3, 4, 7],
    ])

    return vertices, faces


def recoater_mount_block_figure():
    length = 120.0
    width = 25.0
    height = 15.0

    vertices, faces = make_box_mesh(length, width, height)

    fig = go.Figure(
        data=[
            go.Mesh3d(
                x=vertices[:, 0],
                y=vertices[:, 1],
                z=vertices[:, 2],
                i=faces[:, 0],
                j=faces[:, 1],
                k=faces[:, 2],
                opacity=0.9,
                flatshading=True,
                hovertemplate=(
                    "Recoater Mount Block<br>"
                    "120 × 25 × 15 mm<br>"
                    "<extra></extra>"
                ),
            )
        ]
    )

    fig.update_layout(
        margin=dict(l=0, r=0, t=30, b=0),
        scene=dict(
            xaxis_title="Width (mm)",
            yaxis_title="Height (mm)",
            zaxis_title="Length (mm)",
            aspectmode="data",
            camera=dict(
                eye=dict(x=1.6, y=1.3, z=1.1)
            )
        ),
        title="D-012 — 3D reconstruction from 2D evidence",
    )

    return fig


def make_cylinder_mesh(radius, height, segments=96):
    theta = np.linspace(
        0,
        2 * np.pi,
        segments,
        endpoint=False,
    )

    vertices = []

    for z in (-height / 2, height / 2):
        for angle in theta:
            vertices.append([
                radius * np.cos(angle),
                radius * np.sin(angle),
                z,
            ])

    vertices = np.array(vertices)

    bottom = 0
    top = segments

    # Add center points for top/bottom faces
    bottom_center = len(vertices)
    top_center = bottom_center + 1

    vertices = np.vstack([
        vertices,
        [0, 0, -height / 2],
        [0, 0, height / 2],
    ])

    faces = []

    for i in range(segments):
        n = (i + 1) % segments

        # Side wall
        faces.append([bottom + i, bottom + n, top + n])
        faces.append([bottom + i, top + n, top + i])

        # Bottom face
        faces.append([bottom_center, bottom + n, bottom + i])

        # Top face
        faces.append([top_center, top + i, top + n])

    return vertices, np.array(faces)


def build_plate_figure():
    # D-026 main envelope
    radius = 125.0
    thickness = 25.0

    vertices, faces = make_cylinder_mesh(
        radius,
        thickness,
    )

    fig = go.Figure(
        data=[
            go.Mesh3d(
                x=vertices[:, 0],
                y=vertices[:, 1],
                z=vertices[:, 2],
                i=faces[:, 0],
                j=faces[:, 1],
                k=faces[:, 2],
                opacity=0.9,
                flatshading=True,
                hovertemplate=(
                    "Build Plate<br>"
                    "Ø250 mm × 25 mm<br>"
                    "<extra></extra>"
                ),
            )
        ]
    )

    fig.update_layout(
        margin=dict(l=0, r=0, t=30, b=0),
        scene=dict(
            xaxis_title="X (mm)",
            yaxis_title="Y (mm)",
            zaxis_title="Thickness (mm)",
            aspectmode="data",
            camera=dict(
                eye=dict(x=1.4, y=1.4, z=1.0)
            )
        ),
        title="D-026 — 3D reconstruction from 2D evidence",
    )

    return fig


def bygge_base_ring_figure():
    outer_radius = 125.0
    inner_radius = 112.0
    thickness = 3.0
    segments = 128

    theta = np.linspace(
        0,
        2 * np.pi,
        segments,
        endpoint=False,
    )

    vertices = []

    for z in (-thickness / 2, thickness / 2):
        for radius in (outer_radius, inner_radius):
            for angle in theta:
                vertices.append([
                    radius * np.cos(angle),
                    radius * np.sin(angle),
                    z,
                ])

    vertices = np.array(vertices)

    outer_bottom = 0
    inner_bottom = segments
    outer_top = 2 * segments
    inner_top = 3 * segments

    faces = []

    for i in range(segments):
        n = (i + 1) % segments

        # Outer wall
        faces.append([
            outer_bottom + i,
            outer_bottom + n,
            outer_top + n,
        ])
        faces.append([
            outer_bottom + i,
            outer_top + n,
            outer_top + i,
        ])

        # Inner wall
        faces.append([
            inner_bottom + i,
            inner_top + n,
            inner_bottom + n,
        ])
        faces.append([
            inner_bottom + i,
            inner_top + i,
            inner_top + n,
        ])

        # Top ring surface
        faces.append([
            outer_top + i,
            outer_top + n,
            inner_top + n,
        ])
        faces.append([
            outer_top + i,
            inner_top + n,
            inner_top + i,
        ])

        # Bottom ring surface
        faces.append([
            outer_bottom + i,
            inner_bottom + n,
            outer_bottom + n,
        ])
        faces.append([
            outer_bottom + i,
            inner_bottom + i,
            inner_bottom + n,
        ])

    faces = np.array(faces)

    fig = go.Figure(
        data=[
            go.Mesh3d(
                x=vertices[:, 0],
                y=vertices[:, 1],
                z=vertices[:, 2],
                i=faces[:, 0],
                j=faces[:, 1],
                k=faces[:, 2],
                opacity=0.9,
                flatshading=True,
                hovertemplate=(
                    "Bygge Base Ring<br>"
                    "OD 250 mm<br>"
                    "ID 224 mm<br>"
                    "Thickness 3 mm<br>"
                    "<extra></extra>"
                ),
            )
        ]
    )

    fig.update_layout(
        margin=dict(l=0, r=0, t=30, b=0),
        scene=dict(
            xaxis_title="X (mm)",
            yaxis_title="Y (mm)",
            zaxis_title="Thickness (mm)",
            aspectmode="data",
            camera=dict(
                eye=dict(x=1.4, y=1.4, z=1.0)
            )
        ),
        title="D-025 — 3D reconstruction from 2D evidence",
    )

    return fig
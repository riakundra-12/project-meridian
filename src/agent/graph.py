"""Relationship graph over the BOM's 'Interface with' column. Backs
get_interfaces (same shape as before, now graph-backed) and the new
get_interface_network tool for real multi-hop traversal. Also the backend
the knowledge-graph bonus's interactive view (B8) will read from.

Built from the raw BOM directly, not knowledge.json — same "stays out of
the stable schema" choice get_interfaces made in B0, now shared by both.
"""

import networkx as nx

from src.ingestion.load_sources import load_bom

_graph_cache = None


def _resolve_interface_cell(raw, name_lookup: dict) -> list:
    """Splits one BOM row's 'Interface with' free-text cell into resolved
    (real BOM part name) and unresolved (free text with no match) pieces.
    """
    is_empty = raw is None or (isinstance(raw, float) and raw != raw) or str(raw).strip() == ""
    if is_empty:
        return []

    pieces = [p.strip() for p in str(raw).split(",") if p.strip()]
    resolved = []
    for piece in pieces:
        target = name_lookup.get(piece.lower())
        if target:
            resolved.append({"target": target, "resolved": True})
        else:
            resolved.append({"target": piece, "resolved": False, "note": "no matching BOM part name"})
    return resolved


def _build_graph() -> nx.DiGraph:
    global _graph_cache
    if _graph_cache is not None:
        return _graph_cache

    bom = load_bom()
    name_lookup = {n.lower(): n for n in bom["Name"]}

    graph = nx.DiGraph()
    for name in bom["Name"]:
        graph.add_node(name, unresolved_interfaces=[])

    for idx, row in bom.iterrows():
        canonical_name = row["Name"]
        pieces = _resolve_interface_cell(row.get("Interface with"), name_lookup)

        count_cell = row.get("Count (Interface with)")
        try:
            if count_cell is not None and count_cell == count_cell and str(count_cell).strip() != "":
                expected = int(count_cell)
                if expected != len(pieces):
                    print(
                        f"[graph] WARNING: BOM row {idx} ({canonical_name}) declares "
                        f"Count (Interface with)={expected} but comma-split into "
                        f"{len(pieces)} pieces: {pieces}"
                    )
        except (TypeError, ValueError):
            pass

        for piece in pieces:
            if piece["resolved"]:
                graph.add_edge(canonical_name, piece["target"], source_ref=f"BOM row {idx}")
            else:
                graph.nodes[canonical_name]["unresolved_interfaces"].append(piece["target"])

    _graph_cache = graph
    return graph


def get_interfaces(part_name: str) -> dict:
    """Same tool, same return shape as B0's version — now backed by the
    cached graph's 1-hop out-edges instead of re-parsing BOM text every
    call. Zero regression risk to B1/B2.
    """
    graph = _build_graph()
    canonical = next((n for n in graph.nodes if n.lower() == part_name.lower()), None)
    if canonical is None:
        return {"found": False, "part_name": part_name}

    out_edges = list(graph.out_edges(canonical, data=True))
    if not out_edges:
        return {"found": True, "part": {"entity_id": canonical, "fields": {}}}

    interfaces = [{"target": target, "resolved": True} for _, target, _ in out_edges]
    # All edges from one BOM row share the same source_ref (one cell per row).
    source_ref = out_edges[0][2]["source_ref"]

    return {
        "found": True,
        "part": {
            "entity_id": canonical,
            "fields": {
                "interfaces": {
                    "value": interfaces,
                    "source_ref": source_ref,
                    "confidence": 1.0,
                }
            },
        },
    }


def get_interface_network(part_name: str, max_depth: int = 2) -> dict:
    """BFS from part_name's node up to max_depth hops. Returns one entry
    per node reached (including the start node), each shaped identically
    to get_interfaces's single-part shape -- reuses search_parts's
    {results: [...]} envelope so record_grounded_facts needs no changes
    to support it.

    Cycle-safe: networkx's bfs_edges only visits each node once by
    construction, so a real cycle in the data (e.g. Left Side Box <->
    Back Box) cannot cause an infinite loop.
    """
    graph = _build_graph()
    canonical = next((n for n in graph.nodes if n.lower() == part_name.lower()), None)
    if canonical is None:
        return {"found": False, "part_name": part_name}

    visited = {canonical}
    for _, target in nx.bfs_edges(graph, canonical, depth_limit=max_depth):
        visited.add(target)

    results = []
    for node in visited:
        out_edges = list(graph.out_edges(node, data=True))
        fields = {}
        if out_edges:
            fields["interfaces"] = {
                "value": [{"target": t, "resolved": True} for _, t, _ in out_edges],
                "source_ref": out_edges[0][2]["source_ref"],
                "confidence": 1.0,
            }
        results.append({"entity_id": node, "fields": fields})

    return {"found": True, "count": len(results), "results": results}

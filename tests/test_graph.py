"""Unit tests for src/agent/graph.py — real BOM data wherever a real case
exists, a synthetic case only where the real dataset genuinely has none
(checked directly, not assumed: no 'Interface with' cell in the actual
BOM fails to resolve to a real part name).

Run from the repo root: python -m pytest tests/test_graph.py -v
"""

from src.agent.graph import _resolve_interface_cell, get_interfaces, get_interface_network


def test_single_hop_matches_real_data():
    result = get_interfaces("Front Door")
    assert result["found"] is True
    interfaces = result["part"]["fields"]["interfaces"]["value"]
    assert interfaces == [{"target": "Front Side Box", "resolved": True}]
    assert result["part"]["fields"]["interfaces"]["source_ref"] == "BOM row 9"


def test_not_found():
    result = get_interfaces("Not A Real Part")
    assert result == {"found": False, "part_name": "Not A Real Part"}


def test_no_interfaces_recorded():
    # Recoater mount block has an empty 'Interface with' cell in the real BOM.
    result = get_interfaces("Recoater mount block")
    assert result["found"] is True
    assert result["part"]["fields"] == {}


def test_real_cycle_terminates_and_is_correct():
    """Left Side Box <-> Back Box is a genuine cycle in the real BOM data
    (each interfaces with the other, directly or via Top Side). BFS must
    visit each node exactly once, not loop forever."""
    result = get_interface_network("Left Side Box", max_depth=2)
    assert result["found"] is True

    entity_ids = [e["entity_id"] for e in result["results"]]
    assert len(entity_ids) == len(set(entity_ids)), "a node appeared more than once"
    assert "Left Side Box" in entity_ids
    assert "Back Box" in entity_ids

    back_box = next(e for e in result["results"] if e["entity_id"] == "Back Box")
    back_box_targets = {t["target"] for t in back_box["fields"]["interfaces"]["value"]}
    assert "Left Side Box" in back_box_targets  # confirms the cycle edge itself is present


def test_network_not_found():
    result = get_interface_network("Not A Real Part")
    assert result == {"found": False, "part_name": "Not A Real Part"}


def test_resolver_flags_unresolved_targets():
    """No 'Interface with' cell in the real BOM actually fails to resolve
    (checked directly against the live data, not assumed) -- so this
    exercises _resolve_interface_cell's unresolved-target branch directly
    with a synthetic lookup, rather than faking a real-data case that
    doesn't exist."""
    name_lookup = {"front side box": "Front Side Box"}
    result = _resolve_interface_cell("Front Side Box, Some Nonexistent Part", name_lookup)

    assert result == [
        {"target": "Front Side Box", "resolved": True},
        {"target": "Some Nonexistent Part", "resolved": False, "note": "no matching BOM part name"},
    ]

"""Unit tests for src/corrections/store.py. Isolated per-test via
tests/conftest.py's autouse fixture -- never touches the real
data/corrections.json.

Run from the repo root: python -m pytest tests/test_corrections_store.py -v
"""

from src.corrections.store import (
    create_proposal,
    accept_proposal,
    reject_proposal,
    revert_correction,
    get_history,
)


def test_create_accept_round_trip():
    proposal = create_proposal(
        part_name="Front Door",
        field="material",
        current_value="Aluminium",
        proposed_value="Titanium",
        source_ref="BOM row 9",
    )

    accepted = accept_proposal(proposal["id"])
    assert accepted["status"] == "accepted"

    history = get_history()
    assert history["pending"] == []
    assert [item["id"] for item in history["accepted"]] == [proposal["id"]]


def test_create_reject_round_trip():
    proposal = create_proposal(
        part_name="Front Door",
        field="material",
        current_value="Aluminium",
        proposed_value="Unobtainium",
        source_ref="BOM row 9",
    )

    rejected = reject_proposal(proposal["id"])
    assert rejected["status"] == "rejected"

    history = get_history()
    assert [item["id"] for item in history["rejected"]] == [proposal["id"]]


def test_revert_moves_accepted_to_rejected():
    """The actual fix for the gap a lead-engineer-lens audit caught: the
    one prior example of 'undoing' an accepted correction (proposal-3) was
    done by hand-editing data/corrections.json directly, because no code
    path existed to do it. revert_correction is that code path now."""
    proposal = create_proposal(
        part_name="Recoater Blade",
        field="material",
        current_value="Silicone",
        proposed_value="3.3315 (EN-AW 5005)",
        source_ref="drawing:D-013",
    )
    accept_proposal(proposal["id"])

    reverted = revert_correction(proposal["id"], note="false bom_match, confirmed by re-reading the drawing")
    assert reverted["status"] == "rejected"
    assert reverted["reverted_at"] is not None
    assert "false bom_match" in reverted["note"]

    history = get_history()
    assert history["accepted"] == []
    assert [item["id"] for item in history["rejected"]] == [proposal["id"]]


def test_revert_unknown_id_is_a_noop():
    assert revert_correction("proposal-does-not-exist") is None

import json
from pathlib import Path
from datetime import datetime, timezone


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CORRECTIONS_PATH = PROJECT_ROOT / "data" / "corrections.json"


def _load_store():
    if not CORRECTIONS_PATH.exists():
        return {
            "proposals": [],
            "accepted": [],
            "rejected": [],
        }

    with CORRECTIONS_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_store(store):
    CORRECTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)

    with CORRECTIONS_PATH.open("w", encoding="utf-8") as f:
        json.dump(
            store,
            f,
            indent=2,
            ensure_ascii=False,
        )


def create_proposal(
    part_name,
    field,
    current_value,
    proposed_value,
    source_ref,
):
    store = _load_store()

    proposal = {
        "id": f"proposal-{len(store['proposals']) + len(store['accepted']) + len(store['rejected']) + 1}",
        "part_name": part_name,
        "field": field,
        "current_value": current_value,
        "proposed_value": proposed_value,
        "source_ref": source_ref,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    store["proposals"].append(proposal)
    _save_store(store)

    return proposal


def get_pending_proposals():
    return _load_store()["proposals"]


def accept_proposal(proposal_id):
    store = _load_store()

    remaining = []
    accepted = None

    for proposal in store["proposals"]:
        if proposal["id"] == proposal_id:
            proposal["status"] = "accepted"
            proposal["reviewed_at"] = datetime.now(timezone.utc).isoformat()
            accepted = proposal
            store["accepted"].append(proposal)
        else:
            remaining.append(proposal)

    store["proposals"] = remaining
    _save_store(store)

    return accepted


def reject_proposal(proposal_id):
    store = _load_store()

    remaining = []
    rejected = None

    for proposal in store["proposals"]:
        if proposal["id"] == proposal_id:
            proposal["status"] = "rejected"
            proposal["reviewed_at"] = datetime.now(timezone.utc).isoformat()
            rejected = proposal
            store["rejected"].append(proposal)
        else:
            remaining.append(proposal)

    store["proposals"] = remaining
    _save_store(store)

    return rejected


def revert_correction(proposal_id, note=None):
    """Moves an ACCEPTED proposal back into 'rejected', stamped with a
    reverted_at timestamp and an optional note. Previously the only way to
    undo a wrongly-accepted correction was hand-editing data/corrections.json
    directly (see proposal-3's git history) -- this is that same operation,
    through real code, so it's reproducible and doesn't require touching
    the JSON file by hand. Mirrors accept_proposal/reject_proposal's
    find-and-move pattern exactly; no new store shape."""
    store = _load_store()

    remaining = []
    reverted = None

    for item in store["accepted"]:
        if item["id"] == proposal_id:
            item["status"] = "rejected"
            item["reverted_at"] = datetime.now(timezone.utc).isoformat()
            if note:
                item["note"] = note
            reverted = item
            store["rejected"].append(item)
        else:
            remaining.append(item)

    store["accepted"] = remaining
    _save_store(store)

    return reverted


def get_accepted_value(part_name, field):
    store = _load_store()

    matches = [
        item
        for item in store["accepted"]
        if item["part_name"].lower() == part_name.lower()
        and item["field"] == field
    ]

    if not matches:
        return None

    return matches[-1]["proposed_value"]


def get_history():
    store = _load_store()

    return {
        "pending": store["proposals"],
        "accepted": store["accepted"],
        "rejected": store["rejected"],
    }
"""Session-wide test isolation.

Found live (2026-10-09, flagged by a supervisor review): accepting a real
correction through the UI mutates data/corrections.json, which get_part's
correction overlay reads on every call. Any test exercising get_part on a
part that later gets a real correction silently breaks -- this actually
happened (a correction on Front Door broke 5 unrelated tests until the
full suite was re-run and caught it). Autouse fixture points the
corrections store at a fresh temp file for every test, so the real data
file is never read or written by the test suite regardless of what's live
in the running app.
"""

import pytest


@pytest.fixture(autouse=True)
def isolated_corrections_store(tmp_path, monkeypatch):
    import src.corrections.store as store

    monkeypatch.setattr(store, "CORRECTIONS_PATH", tmp_path / "corrections.json")

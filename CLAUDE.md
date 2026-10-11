# Project Meridian — orientation for a Claude Code session

This file was originally (2026-10-08) a gap-audit of the pre-rebuild
submission — GPT-built, zero real LLM calls, the thing Avathon rejected.
Every gap it listed has since been closed (B0–B7, plus a follow-up fix
pass after two independent adversarial audits). Keeping that history here
would just be stale duplication of what `HANDOFF.md` now covers properly
— read that file first, not this one, for "what's actually built and
what's rough." This file is just a pointer + the fast orientation.

## Read these, in order

1. **`HANDOFF.md`** — the real "what do I need to know to pick this up"
   doc. Setup, what's done, known rough edges, the two things that will
   trip you up (model IDs rotting, Gemini's daily quota).
2. **`README.md`** — the submission-facing doc: architecture, features,
   demo questions, disclosure, known limitations.
3. **`CHALLENGE.md`** — the original brief, for checking against either.

## Fast orientation

- Real LLM agent (`src/agent/`), Gemini primary with a live Gemini→Groq
  failover, citation-validated claims-first output — no model-authored
  free text reaches the user unchecked.
- Vision extraction (`src/extraction/`) covers all 30 drawings (4
  hand-curated, 26 via B5), self-consistency confidence, auto-filed
  conflicts into the existing correction queue.
- Real CadQuery 3D (`src/visualization/cadquery_mesh.py`) on top of B5's
  extracted dimensions — 10 parts total have 3D now, 3 hand-built + 7
  generated.
- Governed correction loop, including a real revert path
  (`src/corrections/store.py::revert_correction`) — not hand-editing
  JSON anymore.
- `pytest tests/ -v` — green, grows every time something real gets fixed.
  Don't trust a stale count from memory; run it.

## If you're continuing work here

Don't re-derive context — `HANDOFF.md`'s "What's genuinely not done /
rough edges" section is honest and current. Check it before assuming
something's a bug versus a known, disclosed tradeoff.

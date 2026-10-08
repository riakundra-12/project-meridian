# Project Meridian — working notes for revision

This file orients future work on this repo before it gets resubmitted. The
original brief is `CHALLENGE.md`, the author's own account of the system is
`README.md` (accurate as of last build — it is not aspirational, it describes
what actually runs). This file adds the gap analysis `README.md` doesn't: what
the brief actually requires vs. what the code currently does, so the next pass
of work can be prioritized.

## Problem statement (from `CHALLENGE.md`)

Build a locally runnable app that turns the OpenLPBF v2 (an open-hardware
metal 3D printer) drawing + BOM corpus into a chat-queryable, evidence-cited
knowledge system for an engineer — not a PDF search box.

Hard requirements ("a submission that misses any of them is incomplete"):

1. **Chat over extracted knowledge.** Answers come from structured records
   (not raw PDF stuffed into an LLM context), cite evidence (BOM row /
   drawing / crop), and the system must say "I don't know" / abstain when
   evidence is missing, noisy, or conflicting.
2. **2D + orbitable 3D for ≥3 parts.** Reconstructions must be labeled as
   "reconstructed from 2D evidence," never presented as native CAD.
3. **Chat drives the visual.** Mentioning a part in chat must open/attach its
   drawing (and 3D, if it has one) in the same turn.
4. **One governed correction.** Propose in chat → human accepts/rejects in a
   review UI → accepted answer changes → original evidence + audit history
   stay visible, nothing is silently overwritten.

Bonus (only scored once the required bar is met): supplier discovery beyond
the BOM snapshot, an interactive knowledge graph, a richer multi-type
correction/learning loop.

Dataset (`dataset/`): 30 fabrication drawings across 6 subsystems (Box,
Powder, Recoater, Optical, Gas Flow, Z-axis), a 192-row pinned BOM
(`dataset/context/openlpbf-bom.csv`) with materials/suppliers/costs/V&V
states/free-text `Interface with` relationships, plus upstream context docs.
8 of the 30 drawings are deliberately degraded scans with no clean
counterpart supplied — these exist specifically to test uncertainty handling,
not to be reconstructed in 3D.

## Current architecture (what's actually built)

Streamlit, single-process, no external API/LLM calls at all — "chat" is
deterministic Python string matching, not an LLM.

```
dataset/ (BOM CSV, manifest.json, 30 PDFs, context docs)
        │
src/ingestion/load_sources.py      — reads BOM csv + manifest.json
src/knowledge/build_knowledge.py   — builds data/knowledge.json (run manually /
                                      via run.sh before each launch)
        │  reads CURATED_DRAWINGS (src/knowledge/curated_drawings.py) —
        │  a hand-written dict, only 4 of 30 drawings have any metadata
        ▼
data/knowledge.json  — { "parts": [...192 BOM rows...], "drawings": [...30, mostly empty fields...] }
        │
app.py  — single file, everything lives here:
        │   - find_best_part(): substring match of chat text against part/drawing names
        │   - parse_material_correction(): one regex for "change material of X to Y"
        │   - answer_multi_document_query(): 3 hardcoded query shapes (by Aluminium,
        │     by subsystem+supplier, by subsystem+cost) — exact prefix/suffix string match
        │   - renders PDF page via PyMuPDF, 3D via Plotly (src/visualization/models_3d.py)
        ▼
src/corrections/store.py — data/corrections.json, flat proposal/accepted/rejected lists,
                            overlay applied by get_accepted_value() at answer time
```

Key design choice stated in README: BOM/drawing evidence is immutable;
corrections are an overlay, never a rewrite. This part is real and works as
described.

## What's solid

- Correction loop (req. #4) is genuinely implemented end-to-end: propose in
  chat → `data/corrections.json` pending entry → review UI accept/reject →
  overlay changes the next answer → original BOM value + history stay
  visible. This is the strongest part of the submission.
- 3 parts (D-012 Recoater Mount Block, D-026 Build Plate, D-025 Bygge Base
  Ring) have 2D+3D with explicit "reconstruction, not CAD" labeling (req. #2).
- Chat-opens-drawing wiring (req. #3) works for the 4 curated drawings.
- One deliberate uncertainty demo exists (D-014, `unverified` match status
  with a stated reason) — shows the system can represent conflicting
  identity evidence rather than guessing.
- Deterministic, reproducible, zero cost/latency concerns — fine for a
  judged demo, and honestly reported as such in README's own limitations
  section rather than overclaimed.

## Where this is thin for the actual bar (prioritize here)

**Coverage is the headline problem.** Only 4 of 30 drawings have *any*
curated metadata (`src/knowledge/curated_drawings.py` is a 4-entry dict); the
other 26 drawing records in `knowledge.json` are built with `title`,
`material`, `bom_match`, `match_status` all `None` (see
`build_knowledge.py:84-87` — curated lookup falls through to `{}`).
Practically: chat can only ever resolve a drawing for those 4 IDs, and the
brief explicitly wants "questions across more than one document" and
drawing-to-BOM linking as a general capability, not 4 hardcoded cases. 8 of
the 30 drawings are the intentionally-degraded ones meant to exercise
uncertainty handling — only D-014's sibling-style ambiguity is demonstrated;
the other 7 degraded drawings aren't touched by the app at all.

**"Chat" is substring matching, not language understanding.**
`find_best_part()` (app.py:254) does `part_name in query or query in
part_name`; the multi-document queries (`answer_multi_document_query`,
app.py:101) require exact phrasings like `"Which parts in the Recoater
subsystem have suppliers?"` character-for-character (prefix/suffix string
slicing, not parsing). Anything phrased differently returns the generic
"I could not find a supported structured match" fallback. This will read as
brittle the moment a reviewer deviates from the README's exact example
prompts — and the brief's evaluation criteria explicitly reward
multi-document reasoning and graceful abstention, not exact-match lookup.
Whether to introduce an actual LLM (with disclosure, since the brief requires
disclosing if files go to an external service) or a more general
rule/embedding layer is the central open decision for this revision — see
`CHALLENGE.md`'s "design questions" section, which explicitly invites either.

**No `Interface with` traversal at all.** The BOM column exists in the source
CSV and the brief calls it out twice as a specific thing to support
("component and subsystem interfaces," "free-text interface with evidence");
nothing in `src/` reads that column. This is a named, required-adjacent
capability, not a bonus.

**No knowledge graph, no supplier-discovery bonus, no richer correction
types** — all three bonuses are unstarted. Correctly deprioritized per the
brief ("bonus work is scored only after the required bar is met"), but worth
knowing they're all zero rather than partially started, in case there's time
after the gaps above are closed.

**Degraded-drawing handling is asserted, not demonstrated broadly.** The
manifest (`dataset/manifest.json`) does carry `distribution: degraded-only`
for 8 assets and the app surfaces a `distribution` field in the drawing
panel, but there's no OCR/confidence pipeline or illegibility abstention
logic — README is upfront about this in its own "Known limitations" section.

**Correction coverage is one field, one part-name match style.** Only
`material`, only exact-case-insensitive part-name equality
(`parse_material_correction`, app.py:282) — a real engineer's phrasing like
"the recoater mount block's material should be stainless steel" won't match.
Fine as the single required demo; brittle if treated as representative of a
"richer learning system."

**Evaluation script is a smoke test, not a quality measurement.**
`tests/evaluate_demo.py` checks 5 structural facts about `knowledge.json`
(e.g., "D-012 has verified link"). It doesn't measure answer quality, chat
accuracy, abstention correctness, or anything the brief's "measurements...
about quality, reproducibility, cost, latency, and important failure modes"
section is asking for. The submission doc currently reports this test as if
it is the quality evaluation; it isn't one.

## Suggested revision order

1. Decide the chat-understanding approach (LLM with disclosure, vs. a wider
   deterministic/embedding layer) — this gates everything else and is the
   one open design decision the brief wants justified, not solved by default.
2. Extend curated drawing metadata / BOM-drawing linking beyond 4 IDs — widen
   real multi-document coverage before adding anything bonus.
3. Add `Interface with` traversal — it's named explicitly in the brief, not
   optional polish.
4. Turn `tests/evaluate_demo.py` into something that actually measures
   answer quality/abstention over a question set (`fixtures/public_questions.json`
   is referenced by the brief but doesn't exist in this repo yet — worth
   creating it to drive this).
5. Only then: bonus tier (knowledge graph / supplier discovery / richer
   correction types), if time remains.

## Running it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./run.sh            # rebuilds data/knowledge.json, then `streamlit run app.py`
# → http://localhost:8501
```

`data/knowledge.json` and `data/corrections.json` are build artifacts — the
former is regenerated by `run.sh` every launch, the latter accumulates
proposal history across runs (delete it to reset the correction demo to
empty).

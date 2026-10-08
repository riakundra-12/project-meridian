# Handoff — Project Meridian

For Ria, picking this up cold. This is a status report, not a sales pitch
— everything here is checked against the actual repo state as of this
commit, not what was originally planned. Where something is unverified or
known-rough, it says so.

`README.md` is the submission-facing architecture doc (features, design
decisions, demo workflow). This file is the "what do I actually need to
know to pick this up and keep going" doc — read this one first.

---

## Why this exists

Avathon bounced the original (GPT-built) submission: the chat interface
had zero real LLM calls, just regex/substring matching. Everything in this
repo past the initial commit is the fix — a real tool-calling LLM agent
with citation validation, plus a real vision-extraction pipeline, plus
real 3D generation from that extracted data.

---

## Setup (cold start, assume nothing is configured)

```bash
git clone <this repo>
cd project-meridian
python3.11 -m venv .venv          # 3.11 specifically -- pinned deps, not tested on other versions
source .venv/bin/activate
pip install -r requirements.txt   # heavy install -- CadQuery pulls VTK/numba/scipy, expect a few minutes
cp .env.example .env
```

Edit `.env`:
```
AGENT_PROVIDER=gemini
GEMINI_API_KEY=<get one free at https://aistudio.google.com/apikey>
GROQ_API_KEY=<optional, fallback -- get one free at https://console.groq.com/keys>
EXTRACTION_MODEL=gemini-3.5-flash
```

Then:
```bash
./run.sh
```

If `gemini-3.8-flash` or `gemini-3.5-flash` 404s when you run this —
**that's expected, not a bug in the code.** See "Provider model IDs rot
fast" below.

---

## What's actually done (B0 through B7)

All of this is real, tested, and has evidence you can inspect yourself —
not a claim to take on faith.

- **B0 — Provider spike.** Proved Gemini can do real multi-hop tool-calling
  against our 5(+1) tools. Raw transcripts: `artifacts/b0_transcripts/`.
- **B1 — Chat agent wired into `app.py`.** Replaced the old regex chat
  router with a real tool-calling agent (`src/agent/chat_agent.py`).
- **B2 — Citation validation.** Every claim the agent makes is checked
  against what the tools actually returned that turn
  (`src/agent/validator.py`) before it renders. Citations are shown
  **inline** in the chat text (e.g. "Front Door is made of Aluminium.
  *[BOM row 9]*"), not just enforced invisibly.
- **B3 — README + test harness.** `fixtures/public_questions.json`,
  honest disclosure of what's sent to the LLM (see below — this one
  matters).
- **B4 — Relationship graph.** `src/agent/graph.py`, real `networkx`
  graph over the BOM's `Interface with` column. `get_interface_network`
  tool does real multi-hop traversal in one call. Live-verified including
  a genuine cycle in the real data (Left Side Box ↔ Back Box).
- **B5 — Vision extraction, all 30 drawings.** `src/extraction/`. 4
  drawings are hand-curated (unchanged, still authoritative); the other
  26 have real Gemini vision extraction with 3-run self-consistency.
  Results: `data/extractions/*.json`. 21/30 drawings now have an
  extracted title.
- **B6 — Real CadQuery 3D.** `src/visualization/cadquery_mesh.py`. 7 more
  parts beyond the original 3 hand-built ones now have real 3D, generated
  from B5's extracted dimensions, not hand-tuned. 10 parts with 3D total
  (brief needs 3).
- **B7 — Correction history UI.** Readable per-item cards instead of a
  raw JSON dump, labeled "User-proposed" vs "System-proposed (ingestion)".

**B8 (bonus tier — supplier-finding, interactive knowledge-graph view,
the 5-delta measurement pass) was explicitly skipped**, not forgotten.
The backend for the knowledge-graph bonus already exists
(`get_interface_network`) — only the UI view is missing.

---

## What's genuinely not done / rough edges, not hidden

- **CadQuery only covers `box`/`cylinder`/`ring`.** Drawings whose
  extracted `primitive_type` is `"other"`/`"unknown"` correctly get no 3D
  view rather than a wrong one — `extracted_drawing_figure()` returns
  `None`, never guesses.
- **`bom_match` auto-matching is deliberately conservative.** Only 1 of
  the 26 uncurated drawings auto-matched a BOM part. This isn't a bug —
  it's a real fix for a real bug found live: pure string similarity
  false-matched "Recoater Plate" to a different real part, "Recoater
  Blade", and that false match got **accepted as a correction** before
  being caught and reverted (see `data/corrections.json`'s `rejected`
  list, `proposal-3`, for the full story with a note explaining what
  happened). The threshold was raised afterward; it trades missed
  matches for avoiding wrong ones. If you tune it back down, re-verify
  against real drawings, not just the two example pairs in the code
  comment — that's exactly how the bug got in the first place.
  **One more trap in this same area, found by a second review right
  after the first fix**: changing the threshold does NOT retroactively
  revisit corrections already accepted under the old one.
  `proposal-1` (Window Frame) was filed under the old 0.6 cutoff and is
  still accepted even though D-005 now reads `unmatched` at 0.9 — checked
  by hand (re-read the actual drawing, judged it genuinely plausible, not
  a confirmed error like `proposal-3`) and kept, with a note on the
  correction explaining why. If you touch this threshold again, go check
  `data/corrections.json`'s `accepted` list against the new
  `knowledge.json` match results afterward — don't assume they're still
  consistent.
- **Groq's `gpt-oss-120b` has a real, observed ~1-in-3 quirk**: it
  sometimes emits a tool call named `"commentary"` (an internal
  channel-naming leak), which Groq's strict validation rejects. There's a
  bare retry for this in `GroqProvider._call_model` — reproduced it live
  3 times to confirm it's sampling noise, not persistent, before adding
  the retry. If you see `groq.BadRequestError` about `"commentary"` not
  being retried away, that's a new variant, not the one already handled.
- **Degraded drawings never auto-promote**, by design — confidence is
  forced low regardless of what the self-consistency runs agreed on.
  Don't "fix" this by lowering the threshold for them specifically; it's
  intentional caution on the 8 genuinely degraded source documents.
- **Test isolation**: `tests/conftest.py` points the corrections store at
  a temp file for every test run, so accepting a correction in the live
  UI can't silently break the test suite. This was added *after* it
  actually happened once this session — if you add new code that touches
  `data/*.json` directly instead of going through the existing store
  functions, double check it's covered by the same isolation.

---

## Disclosure — what actually goes to an external LLM

This matters because it's exactly what the original submission got
rejected for not doing. Read `README.md`'s "Models, services, and
external data" section for the full picture, but the short version:

- **Chat**: only structured JSON leaves the machine (tool definitions,
  tool-call results). No PDFs, no images, ever, for a chat turn.
- **Extraction** (`src/extraction/`, offline/one-time per drawing): this
  **does** send the rendered drawing image to Gemini. That's necessary —
  reading a title block requires vision input — and it's disclosed
  plainly, not buried. If you extend extraction further, keep this
  disclosure accurate; an earlier draft of the README claimed "no image
  is ever sent," which stopped being true the moment this pipeline
  shipped and had to be corrected.

---

## Two things that will trip you up if you don't know them going in

**1. Provider model IDs rot fast.** Over the course of building this,
`gemini-2.5-flash` 404'd (deprecated for new users), then
`llama-3.3-70b-versatile` 404'd on Groq (fully removed from the catalog,
not just slow). If a pinned model ID in `.env` or the provider code
404s, don't assume the code is broken — query the live catalog first:

```python
from google import genai
client = genai.Client(api_key="...")
for m in client.models.list():
    print(m.name)
```

(Groq: `client.models.list()` on the `groq` SDK client, same idea.)

**2. Gemini's free tier is capped at 20 requests/day, per model name —
not shared across models.** This was found the hard way, twice. If you
need more throughput in one session (e.g. re-running extraction), you
can point `EXTRACTION_MODEL` or the chat provider at a different real
model name (e.g. `gemini-3.6-flash`, `gemini-3.1-flash-lite`) and get a
fresh pool, confirmed empirically to work — that's literally how B5's
full 26-drawing extraction got finished in one session instead of
spanning days. It's not officially documented behavior, so verify it
still holds before relying on it; APIs change. The retry logic in
`src/agent/gemini_retry.py` already fails fast with a clear error on a
real daily-cap 429 (checked: Google suggests waits of hours for these,
and blindly sleeping through that used to hang the process for real
before this was fixed) rather than hanging — if you see that error,
switching models or waiting is the fix, not debugging the code.

---

## Running the tests

```bash
python -m pytest tests/ -v          # fast, deterministic, no network -- 43 passed, 1 xfail expected
python tests/evaluate_demo.py       # original smoke test, still works
python -m src.agent.b0_spike --scenario all --provider gemini   # live, needs quota
```

The one `xfail` (`test_disputed_field_cited_as_settled_fails`) is
intentional — it documents a validator case with no real trigger yet
(no BOM-vs-drawing conflict-detection exists until a future upgrade), not
a failing test being hidden.

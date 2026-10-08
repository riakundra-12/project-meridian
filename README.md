# Project Meridian

Evidence-grounded engineering intelligence for the OpenLPBF v2 machine.

Project Meridian is a locally runnable Streamlit application that turns a pinned
OpenLPBF bill of materials and engineering drawing corpus into an inspectable,
correctable engineering knowledge interface, answered by a real tool-calling
LLM agent whose every claim is checked against the structured evidence before
it renders.

The system is designed around one principle:

> Source evidence is preserved separately from interpreted or corrected knowledge.

Rather than treating PDFs as a raw retrieval corpus, Meridian builds structured
records from the supplied BOM and drawing manifest, keeps provenance attached to
claims, exposes source drawings in the UI, and supports human-reviewed corrections.

---

## Features

### Chat over structured engineering knowledge, answered by a real LLM agent

Chat is answered by a tool-calling agent (Gemini primary, Groq fallback — see
[Models, services, and external data](#models-services-and-external-data))
with five read-only tools over the structured knowledge: `get_part`,
`search_parts`, `get_drawing`, `get_interfaces`, `list_corrections`. The model
never writes free text directly — it must emit structured claims
(`submit_final_answer(claims, abstain)`), each one copying its value and
source citation verbatim from a tool result. A deterministic Python validator
(no second LLM call) then checks every claim's full
`(entity_id, field, value, source_ref)` tuple against what the tools actually
returned *this turn*, before anything renders. A claim that fails is dropped
silently from the answer, not shown — the rendered answer only ever contains
claims that passed.

Examples:

- `Tell me about the Recoater mount block`
- `What material is the Front Door made of?`
- `What does the Front Door interface with, and what subsystem is that other part in?` — a genuine **multi-hop** question: the agent calls `get_interfaces` to resolve the free-text `Interface with` cell to a canonical part name, then a second tool call (`get_part`) to fetch that part's subsystem, citing both BOM rows independently.

If one or more claims get dropped by the validator but at least one survives,
the answer still renders with a `[N unverified claims dropped]` note rather
than failing the whole turn. If zero claims survive, or the model itself
decides to abstain, the app says so plainly instead of showing an empty or
fabricated answer.

The application never places supplied PDFs or images directly into the LLM's
context window — only structured JSON (part/drawing field values and their
citations) ever leaves the machine. See
[Models, services, and external data](#models-services-and-external-data).

---

### Chat-driven drawing evidence

When a supported part or curated drawing is mentioned in chat, the corresponding
engineering drawing is automatically displayed.

The UI keeps BOM evidence and drawing evidence separate so that a user can inspect
where a claim came from.

Examples:

- Recoater Mount Block → `D-012`
- Build Plate → `D-026`
- Bygge Base Ring → `D-025`
- Recoater Linear Plate → `D-014`

---

### Orbitable 3D reconstruction

Three parts include interactive Plotly 3D reconstructions:

| Drawing | Part | Reconstruction |
|---|---|---|
| D-012 | Recoater Mount Block | 120 × 25 × 15 mm main block envelope |
| D-026 | Build Plate | Ø250 mm circular plate envelope |
| D-025 | Bygge Base Ring | Ø250 / Ø224 mm ring envelope |

Every 3D view is explicitly labeled:

> Reconstructed from the supplied 2D drawing evidence. This is not native CAD.

The current reconstructions intentionally model the major geometric envelope only.
Fine details such as threaded holes, countersinks, and all machining features are
not represented.

---

## Human-reviewed correction workflow

Meridian supports a governed correction flow.

Example:

```text
Change the material of Recoater mount block to Stainless steel
```

The system:

1. Detects the proposed correction.
2. Creates a pending proposal.
3. Preserves the original BOM value and evidence.
4. Shows the proposal in a separate review panel.
5. Allows a human reviewer to Accept or Reject it.
6. Applies accepted corrections as an overlay on future answers.
7. Keeps the original source evidence visible.
8. Retains accepted/rejected history.

The original `knowledge.json` source record is never silently rewritten.

A supported correction command currently follows this form:

```text
Change the material of <part name> to <new material>
```

This intentionally demonstrates one governed update type rather than pretending to
support arbitrary schema mutation.

---

## Uncertainty and conflicting evidence

The application does not assume that similar names automatically identify the same
physical component.

For example, `D-014` has:

- upstream source filename: `RecoaterStagePlate.pdf`
- drawing title: `Recoater Linear Plate`
- a similarly named BOM row: `Recoater stage plate`

Meridian therefore marks this relationship as:

```text
unverified
```

and displays a warning instead of treating the identity as confirmed.

Similarly, `D-025 — Bygge Base Ring` can be inspected by drawing title even though
no verified BOM mapping is currently recorded.

This allows the application to expose useful drawing evidence without inventing a
BOM relationship.

Beyond these hand-curated cases, the agent abstains cleanly on the 26 of 30
drawings that have no curated metadata at all. Asking about, e.g., `D-001`
returns a plain statement that the title/material aren't recorded — not a
plausible-looking guess. This is the citation validator working as designed:
a claim with no matching grounded fact is dropped before it ever renders.

---

# Architecture

```text
Supplied corpus
│
├── BOM CSV
├── manifest.json
├── engineering drawings
└── context / attribution files
        │
        ▼
Source ingestion
        │
        ▼
Structured knowledge
│
├── BOM part records
├── drawing records
├── evidence references
└── curated verified/unverified links
        │
        ▼
Tool-calling LLM agent (Gemini primary, Groq fallback)
        │
        ├── get_part / search_parts / get_drawing / get_interfaces / list_corrections
        │       (read-only; get_part/search_parts overlay any accepted correction)
        ▼
submit_final_answer(claims, abstain) — structured claims only, no free text
        │
        ▼
Citation validator (deterministic Python, no second LLM call)
        │
        └── per claim: (entity_id, field, value, source_ref) must exactly
            match what a tool call actually returned this turn, else dropped
        │
        ▼
Streamlit UI
│
├── chat (rendered from validated claims only)
├── source drawing + 3D (opened from the claims' entity IDs, same turn)
└── correction review
        │
        ▼
Correction overlay
│
├── pending
├── accepted
└── rejected history
```

A proposed correction (`Change the material of X to Y`) is handled by a
separate, deterministic regex path — not the LLM — since it is a write/
governance action, not a knowledge query the agent should be trusted to
initiate on its own.

---

## Key design decisions

### 1. Treat the corpus as evidence, not unquestioned truth

The supplied BOM and drawings are immutable source evidence.

Corrections and interpretation are layered above them rather than overwriting the
original records.

### 2. Structured knowledge before chat

BOM rows are normalized into structured part records containing fields such as:

- name
- subsystem / part family
- type
- material
- supplier
- amount
- cost
- BOM row
- provenance evidence

This means responses come from explicit records rather than raw-document generation.

### 3. Separate drawing claims from BOM claims

A material value observed in a drawing is not automatically treated as identical to
the material value stored in the BOM.

This makes disagreements visible.

### 4. Conservative drawing-to-BOM linking

Only links with sufficient evidence are marked `verified`.

Other relationships may be marked:

- `unverified`
- `unmatched`

This prevents filename similarity alone from becoming a false identity assertion.

### 5. Reconstruction rather than CAD inference

The supplied corpus does not contain native CAD models.

The 3D implementation therefore reconstructs useful major geometry from drawing
dimensions while explicitly exposing its limitations.

### 6. Tool-calling agent, not RAG, and claims-first output

The brief explicitly rules out stuffing PDFs into a context window and
dumping retrieved pages. At this corpus size (192 BOM rows, 4 curated
drawings) a semantic-search/embedding layer adds complexity without adding
correctness — a tool-calling agent over deterministic lookups is simpler and
strictly more inspectable, so there is no embedding/RAG layer anywhere in the
chat path.

The agent is also never allowed to emit free-text prose directly. It must
call `submit_final_answer` with a list of structured claims, each copying a
value and citation verbatim from a tool result; the rendered answer is the
concatenation of whatever claims survive the deterministic validator. This
is a deliberately "robotic but accurate" design: a claim that doesn't match
what a tool actually returned this turn is dropped, not shown — hallucination
risk is bounded by a Python equality check, not by trusting the model.

---

# Dataset coverage

The ingestion layer currently loads:

- **192 BOM rows**
- **30 engineering drawings**
- **40 manifest assets**

The supplied drawing set spans:

- Box
- Powder
- Recoater
- Optical
- Gas Flow
- Z-axis

Advanced drawing metadata has been manually curated only where needed for the
demonstrated workflows.

This is intentional: the project favors a smaller inspectable system over
unverified automated claims.

---

# Project structure

```text
project-meridian/
│
├── app.py
├── README.md
├── CHALLENGE.md
├── ATTRIBUTION.md
├── requirements.txt
├── run.sh
├── .env.example           # copy to .env, fill in GEMINI_API_KEY / GROQ_API_KEY
│
├── screenshots/
│   ├── 01_recoater_mount_block_drawing.png
│   ├── 02_recoater_mount_block_3d.png
│   └── ... additional saved demo outputs
│
├── data/
│   ├── knowledge.json
│   └── corrections.json        # created when corrections are proposed
│
├── dataset/
│   ├── manifest.json
│   ├── drawings/
│   └── context/
│
├── src/
│   ├── ingestion/
│   │   └── load_sources.py
│   │
│   ├── knowledge/
│   │   ├── build_knowledge.py
│   │   ├── models.py
│   │   ├── drawings.py
│   │   └── curated_drawings.py
│   │
│   ├── agent/
│   │   ├── tools.py          # the 5 tool implementations + schemas
│   │   ├── shapes.py         # pivots records into {entity_id, fields} for citation checking
│   │   ├── provider.py       # AGENT_PROVIDER=gemini|groq|hf|mock abstraction
│   │   ├── prompts.py        # the system prompt (forces multi-hop chaining)
│   │   ├── chat_agent.py     # the real per-turn loop app.py calls
│   │   ├── validator.py      # the deterministic citation validator
│   │   ├── transcript.py     # GATE-proof transcript recorder
│   │   └── b0_spike.py       # CLI spike/regression runner, also the injection-check scenario
│   │
│   ├── corrections/
│   │   └── store.py
│   │
│   └── visualization/
│       └── models_3d.py
│
├── fixtures/
│   └── public_questions.json
│
├── artifacts/
│   └── b0_transcripts/       # raw tool-call transcripts, saved proof the agent works
│
└── tests/
    ├── evaluate_demo.py          # original deterministic smoke test (unchanged)
    ├── test_validator.py         # pure unit tests, no network
    └── test_chat_agent_mock.py   # AGENT_PROVIDER=mock regression tests
```

---

# Setup

## Requirements

Tested with:

```text
Python 3.11
```

A local Python virtual environment is recommended.

### 1. Create and activate an environment

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Build the structured knowledge artifact

```bash
python -m src.knowledge.build_knowledge
```

Expected output:

```text
Built 192 part records
Built 30 drawing records
Saved knowledge to: .../data/knowledge.json
```

### 4. Configure the chat agent's LLM provider

Chat is answered by a real LLM tool-calling agent — see
[Models, services, and external data](#models-services-and-external-data)
for exactly what that means and what leaves the machine.

```bash
cp .env.example .env
```

Edit `.env`:

```text
AGENT_PROVIDER=gemini
GEMINI_API_KEY=<your key from https://aistudio.google.com/apikey>
GROQ_API_KEY=<optional, your key from https://console.groq.com/keys>
```

`AGENT_PROVIDER` selects the backend: `gemini` (primary), `groq` (fallback),
`mock` (scripted, deterministic, used by the test suite — not usable for
answering arbitrary questions). Without a valid key for the selected
provider, the app shows a clear setup message in chat instead of crashing.

### 5. Launch the app

Preferred simple start script:

```bash
./run.sh
```

This activates the local virtual environment, rebuilds the structured knowledge
artifact, and launches Streamlit.

You can also launch manually with:

```bash
streamlit run app.py
```

Then open:

```text
http://localhost:8501
```

---

# Demo workflow

## Verified BOM + drawing + 3D

Ask:

```text
Tell me about the Recoater mount block
```

Expected:

- structured BOM answer
- source BOM row
- `D-012`
- source drawing
- orbitable 3D reconstruction

---

## Second reconstructed part

Ask:

```text
Tell me about the Build Plate
```

Expected:

- structured BOM answer
- `D-026`
- drawing
- orbitable 3D reconstruction

---

## Drawing without invented BOM identity

Ask:

```text
Tell me about the Bygge Base Ring
```

Expected:

- `D-025`
- source drawing
- orbitable 3D reconstruction
- explicit statement that no verified BOM mapping is recorded

---

## Conflicting identity evidence

Ask:

```text
Tell me about the Recoater Linear Plate
```

Expected:

- `D-014`
- source drawing
- `unverified` relationship status
- visible warning explaining the filename / title / BOM ambiguity

---

## Multi-hop interface reasoning

Ask:

```text
What does the Front Door interface with, and what subsystem is that other part in?
```

Expected: the agent calls `get_interfaces("Front Door")`, resolving the raw
BOM `Interface with` cell to `Front Side Box`, then makes a **second** tool
call, `get_part("Front Side Box")`, to answer the second half of the
question. Both claims cite their own BOM row independently (`BOM row 9` and
`BOM row 13`). This is a real multi-hop tool chain, not a canned two-part
answer — verified against the raw transcripts in `artifacts/b0_transcripts/`.

## Abstention on uncurated data

Ask:

```text
What is the title and material of drawing D-001?
```

Expected: the agent calls `get_drawing("D-001")`, finds no curated
title/material for this drawing (26 of 30 are uncurated), and says so rather
than fabricating a plausible-looking answer — `abstain: true`, zero claims
rendered.

## Governed correction

First ask:

```text
Tell me about the Recoater mount block
```

Then propose:

```text
Change the material of Recoater mount block to Stainless steel
```

Review the proposal in the **Correction review** section and click **Accept**.

Ask again:

```text
Tell me about the Recoater mount block
```

The answer should show the accepted corrected material while still displaying the
original BOM evidence.

---

## Multi-document BOM queries

Meridian also supports several cross-record questions over the structured BOM.

Examples:

```text
Which parts use Aluminium?
```

```text
Which parts in the Recoater subsystem have suppliers?
```

```text
What are the recorded costs for parts in the Recoater subsystem?
```

These responses aggregate multiple BOM records, preserve source BOM row references,
and include caveats that supplier and cost information comes from the pinned snapshot.

---

# Evaluation

A lightweight deterministic evaluation script is included:

```bash
python tests/evaluate_demo.py
```

Current expected result:

```text
PASS: Recoater Mount Block exists in BOM
PASS: D-012 has verified link
PASS: D-026 Build Plate exists
PASS: D-025 is intentionally unmatched
PASS: D-014 remains unverified

5/5 checks passed
```

The checks intentionally validate provenance and identity decisions rather than only
testing whether strings can be retrieved.

A second, pytest-based suite covers the citation validator and the chat
agent's loop logic — no network, no LLM, deterministic:

```bash
pip install pytest  # already in requirements.txt
python -m pytest tests/test_validator.py tests/test_chat_agent_mock.py -v
```

Expected: `10 passed, 1 xfailed` — the one `xfail` is an honestly-documented
gap (a "disputed field cited as settled" case with no real trigger yet,
since conflict detection isn't built — see Known limitations), not a failing
test being hidden.

A separate CLI runner exercises the full agent against a real LLM provider
and saves the raw tool-call transcript as proof, rather than a claim that it
works:

```bash
python -m src.agent.b0_spike --scenario all --provider gemini
```

---

# Quality and reproducibility observations

These are real measurements from running the agent, not projected estimates.

### Reproducibility

The supplied corpus is pinned by the provided manifest and source revision;
ingestion (`build_knowledge.py`) is fully deterministic and local.

The chat agent's LLM call is **not** bit-reproducible — the same question can
produce a different tool-call sequence between runs (observed directly: the
model sometimes makes an extra, unprompted `list_corrections` check before
finalizing an answer that didn't need one). This doesn't affect correctness,
since every claim is still checked against this turn's actual tool results
regardless of sequence — but it means "same input → same exact wording" is
not a property this system has, only "same input → an answer that, if
present, is grounded."

### Latency

BOM/drawing lookups and PDF/3D rendering are local and interactive. The LLM
call is the real latency cost: a single-hop question is typically a few
seconds; the multi-hop interface question observed 2 tool-call round trips
plus the final answer call, each a few seconds, for roughly 5-15s total
depending on provider load.

### Cost

**$0 in direct spend** — both configured providers (Gemini, Groq) are used on
their free tiers, no paid API anywhere.

**But not unlimited**, and this is a real, load-bearing limitation, not a
footnote: Gemini's free tier caps `gemini-3.8-flash` at **20 requests per
day** (confirmed by hitting it directly during development, not from
documentation) on top of a 5 requests/minute throttle. A single multi-hop
chat turn can cost 2-4 of those 20 daily requests. Groq is the fallback
specifically because its published limits (30 RPM / 1,000 requests/day for
70B-class models) are far more headroom, though — disclosed plainly — Groq's
tool-calling behavior on this exact tool set has not yet been exercised
against a live multi-hop question the way Gemini's has.

### Trust

Important claims expose:

- BOM row provenance (or `correction:<id>` when an accepted correction overrides it)
- drawing identifier
- drawing source quality
- relationship status
- original values after correction

Beyond that, every claim the chat agent renders has already passed a
deterministic check against this turn's actual tool outputs — a claim that
doesn't match is dropped before it's ever shown, not just caveated.
Unsupported or ambiguous links are not upgraded to verified facts.

---

# Known limitations

### LLM provider quota is a real ceiling, not a footnote

Gemini's free tier caps `gemini-3.8-flash` at **20 requests/day** —
confirmed directly, not assumed. Heavy testing or a long interactive demo
session can exhaust it; the app fails fast with a clear error rather than
hanging when that happens (an earlier version of the retry logic did hang,
for up to the ~2-hour delay Google's API suggests — fixed to cap any single
retry wait at 60s). `AGENT_PROVIDER=groq` is the documented fallback but its
real behavior on this exact tool set has only been exercised in isolated
testing, not a full live multi-hop run, at time of writing.

### Natural-language understanding

Chat is answered by a real tool-calling LLM agent (not deterministic string
matching) over the 5 defined tools, so it handles genuine natural-language
variation and multi-hop questions the original deterministic router could
not. It is still bounded by what the tools can return: `get_interfaces` is a
raw BOM-cell lookup, not graph traversal (no transitive "what does X
ultimately connect to through Y" reasoning beyond what a tool call directly
returns), and `search_parts`/`get_part` are exact/substring matches, not
fuzzy semantic search.

### Multi-document reasoning

The chat supports cross-record BOM queries, including:

- parts sharing a recorded material;
- parts in a subsystem with recorded suppliers;
- recorded costs for parts in a subsystem;
- multi-hop interface questions (an entity's interfacing part's own fields).

Example prompts:

```text
Which parts use Aluminium?
```

```text
Which parts in the Recoater subsystem have suppliers?
```

```text
What does the Front Door interface with, and what subsystem is that other part in?
```

Each result preserves BOM row provenance (or `correction:<id>` when a
correction overrides a field), and every claim is checked against this
turn's actual tool outputs before rendering.

Current limitation: `get_interfaces` ships as a raw same-row BOM lookup
(every one of this component's immediate `Interface with` text, nothing
beyond one hop automatically) rather than a real relationship graph — full
graph traversal and the knowledge-graph bonus are future-track work.

### Drawing extraction

Not all 30 drawings have been manually normalized into detailed structured drawing
fields.

Only selected drawings have curated title/material/link metadata for the demonstrated
workflows.

### 3D reconstruction

Three parts have orbitable reconstructions, but the models capture the main geometric
envelope rather than every manufacturing feature.

Examples of currently omitted geometry include:

- threaded holes
- countersinks
- fine machining reliefs
- tolerances
- complete feature placement

They must not be interpreted as production CAD.

### Correction types

The governed correction workflow currently demonstrates material updates only.

A broader production implementation would support typed updates across additional
fields with stronger validation and reviewer identity/audit metadata.

### Degraded drawings

The manifest preserves which drawings are degraded, but the current prototype does
not implement a full OCR/confidence pipeline across all noisy drawings.

The application instead demonstrates conservative uncertainty handling through
explicit source-quality and relationship status.

### Procurement information

Supplier and cost values shown by the app come from the supplied pinned BOM snapshot.

They should not be interpreted as current supplier availability or pricing.

---

# Models, services, and external data

**The chat agent uses an external LLM.** This is a deliberate, disclosed
choice — the brief requires chat answers to come from real extracted
knowledge with citations and abstention, and a tool-calling LLM is how that
reasoning (including genuine multi-hop chaining) is implemented here.

- **Provider abstraction, `AGENT_PROVIDER` env var** — the same tool-calling
  interface works regardless of backend. No code change needed to switch
  providers, only `.env`.
- **Primary: Gemini** (`gemini-3.8-flash`, via Google's `google-genai` SDK),
  free tier. Confirmed via live testing to correctly perform real multi-hop
  tool chaining (see `artifacts/b0_transcripts/`), not just single-tool
  lookups. Free tier is capped at 20 requests/day — see Known limitations.
- **Fallback: Groq** (`llama-3.3-70b-versatile`, via the official `groq`
  SDK), free tier. Implemented with the same forced tool-calling contract;
  not yet exercised against a live multi-hop question at time of writing —
  disclosed, not hidden.
- **`mock`**: a scripted, deterministic provider used only by the automated
  test suite. Cannot answer arbitrary questions — not a usable fallback for
  real chat.
- **Zero Anthropic/Claude dependency anywhere** in the running app.

**What actually leaves the machine:** only structured JSON — the tool
definitions, and each tool call's small JSON result (part/drawing field
values, their BOM-row or correction citations, correction-proposal
records). **No supplied PDF, image, or raw document text is ever sent to the
LLM.** The 2D/3D rendering pipeline (PyMuPDF, Plotly, NumPy) is entirely
local and never touches the chat agent.

Other main libraries:

- Streamlit — local application UI
- pandas — BOM ingestion
- PyMuPDF — local PDF rendering
- Plotly — orbitable 3D visualization
- NumPy — 3D geometry construction

The application does not currently enrich the pinned supplier data with current web
procurement information.

---

# Future work

Given additional time, the next improvements would be:

1. real relationship-graph traversal over `Interface with` (currently a raw
   same-row lookup), doubling as the knowledge-graph bonus backend;
2. vision-LLM structured extraction of dimensions, tolerances, notes, and
   materials for the 26 currently-uncurated drawings;
3. replacing the hand-built Plotly meshes with CadQuery-generated geometry
   from extracted dimensions, including holes and countersinks;
4. a live-tested Groq run against the real multi-hop case, not just
   isolated testing;
5. extraction-confidence scoring (self-consistency across repeated
   extraction runs) for degraded drawings;
6. broader typed correction workflows beyond material;
7. the supplier-finding and richer-learning-system bonus tiers;
8. a concrete before/after measurement pass (coverage, phrasing robustness,
   citation-validity rate, conflict-detection coverage, cost/latency) now
   that there is a real baseline to measure against.


---

# Saved screenshots

Representative outputs are saved in `screenshots/`:

- `01_recoater_mount_block_drawing.png`
- `02_recoater_mount_block_3d.png`
- `03_build_plate_drawing.png`
- `04_build_plate_3d.png`
- `05_bygge_base_ring_drawing.png`
- `06_bygge_base_ring_3d.png`
- `07_d014_uncertainty.png`
- `08_correction_chat_proposal.png`
- `09_correction_review.png`
- `10_correction_after_acceptance.png`
- `11_multi_document_material_query.png`

These cover the required chat-to-drawing flow, all three reconstructed parts,
uncertainty handling, the governed correction before/after, and a multi-document
query.

---

# Attribution

The engineering dataset is based on third-party OpenLPBF open-hardware material.

See:

- `ATTRIBUTION.md`
- `dataset/context/OpenLPBF-LICENSE.md`
- `dataset/manifest.json`

for source, license, and provenance information.

The original challenge brief is preserved in `CHALLENGE.md`.

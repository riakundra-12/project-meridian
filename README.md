# Project Meridian

Evidence-grounded engineering intelligence for the OpenLPBF v2 machine.

Project Meridian is a locally runnable Streamlit application that turns a pinned
OpenLPBF bill of materials and engineering drawing corpus into an inspectable,
correctable engineering knowledge interface.

The system is designed around one principle:

> Source evidence is preserved separately from interpreted or corrected knowledge.

Rather than treating PDFs as a raw retrieval corpus, Meridian builds structured
records from the supplied BOM and drawing manifest, keeps provenance attached to
claims, exposes source drawings in the UI, and supports human-reviewed corrections.

---

## Features

### Chat over structured engineering knowledge

Users can ask about components in natural language, for example:

- `Tell me about the Recoater mount block`
- `Tell me about the Build Plate`
- `Tell me about the Bygge Base Ring`
- `Tell me about the Recoater Linear Plate`

For BOM-backed parts, answers are generated from structured BOM records and include
the source BOM row.

The application does not place supplied PDFs directly into an LLM context window.

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
Query / routing layer
        │
        ├── BOM-backed part lookup
        └── curated drawing-title lookup
        │
        ▼
Streamlit UI
│
├── chat
├── source drawing
├── 3D reconstruction
└── correction review
        │
        ▼
Correction overlay
│
├── pending
├── accepted
└── rejected history
```

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
│   ├── corrections/
│   │   └── store.py
│   │
│   └── visualization/
│       └── models_3d.py
│
└── tests/
    └── evaluate_demo.py
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

### 4. Launch the app

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

No external API key is required for the current implementation.

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

---

# Quality and reproducibility observations

### Reproducibility

The supplied corpus is pinned by the provided manifest and source revision.

The application uses deterministic local ingestion and does not require an online
model or paid API.

The same supplied files should therefore generate the same structured knowledge
artifact.

### Latency

BOM and drawing routing are local lookups and are effectively interactive for this
small corpus.

PDF page rendering and Plotly geometry generation occur locally.

No external network round trip is required for the demonstrated workflows.

### Cost

The current implementation has no per-query model/API cost.

It uses local Python libraries and the supplied corpus only.

### Trust

Important claims expose:

- BOM row provenance
- drawing identifier
- drawing source quality
- relationship status
- original values after correction

Unsupported or ambiguous links are not upgraded to verified facts.

---

# Known limitations

### Natural-language understanding

The chat router currently performs deterministic name matching rather than general
semantic language understanding.

Queries work best when they name a component.

### Multi-document reasoning

The chat supports several deterministic cross-record BOM queries, including:

- parts sharing a recorded material;
- parts in a subsystem with recorded suppliers;
- recorded costs for parts in a subsystem.

Example prompts:

```text
Which parts use Aluminium?
```

```text
Which parts in the Recoater subsystem have suppliers?
```

```text
What are the recorded costs for parts in the Recoater subsystem?
```

These answers aggregate multiple structured BOM rows and preserve BOM row provenance
for each returned result.

Current limitations remain: the chat does not yet support arbitrary graph traversal
across every `Interface with` relationship or unrestricted natural-language
aggregation.

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

The current implementation does **not** use an external LLM or paid inference API.

Main libraries include:

- Streamlit — local application UI
- pandas — BOM ingestion
- PyMuPDF — local PDF rendering
- Plotly — orbitable 3D visualization
- NumPy — 3D geometry construction

No supplied engineering document is transmitted to an external AI service.

The application does not currently enrich the pinned supplier data with current web
procurement information.

---

# Future work

Given additional time, the next improvements would be:

1. structured extraction of dimensions, tolerances, notes, and materials for more drawings;
2. semantic/fuzzy query interpretation over the structured records;
3. traversal of `Interface with` relationships;
4. material and supplier comparison questions across multiple BOM rows;
5. extraction-confidence scoring for degraded drawings;
6. richer parametric 3D geometry including holes and countersinks;
7. broader typed correction workflows;
8. automated regression evaluation over a representative question set;
9. optional supplier enrichment with clearly separated current external evidence.


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

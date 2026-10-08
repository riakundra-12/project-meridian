import json
from pathlib import Path

import streamlit as st
import pymupdf
from src.visualization.models_3d import (
    recoater_mount_block_figure,
    build_plate_figure,
    bygge_base_ring_figure,
)

import re

from src.corrections.store import (
    create_proposal,
    get_pending_proposals,
    accept_proposal,
    reject_proposal,
    get_accepted_value,
    get_history,
)


PROJECT_ROOT = Path(__file__).resolve().parent
KNOWLEDGE_PATH = PROJECT_ROOT / "data" / "knowledge.json"


@st.cache_data
def load_knowledge():
    with KNOWLEDGE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)

@st.cache_data
def render_pdf_page(pdf_path: str, page_number: int = 0):
    pdf = pymupdf.open(pdf_path)
    page = pdf[page_number]

    pix = page.get_pixmap(matrix=pymupdf.Matrix(1.8, 1.8))

    return pix.tobytes("png")


def find_parts(parts, query):
    query = query.lower().strip()

    if not query:
        return []

    return [
        part
        for part in parts
        if query in part["name"].lower()
    ]


def find_drawing_for_part(drawings, part_name):
    for drawing in drawings:
        bom_match = drawing.get("bom_match")

        if (
            bom_match
            and bom_match.lower() == part_name.lower()
            and drawing.get("match_status") == "verified"
        ):
            return drawing

    return None

def answer_for_part(part):
    original_material = part["material"]

    accepted_material = get_accepted_value(
        part["name"],
        "material",
    )

    effective_material = (
        accepted_material
        if accepted_material is not None
        else original_material
    )

    lines = [
        f"**{part['name']}** belongs to the **{part['subsystem']}** subsystem.",
        f"- Type: {part['part_type'] or 'Not recorded'}",
        f"- Material: {effective_material or 'Not recorded'}",
        f"- Supplier: {part['supplier'] or 'Not recorded'}",
        f"- Amount: {part['amount'] if part['amount'] is not None else 'Not recorded'}",
        f"- Cost: {part['cost'] or 'Not recorded'}",
        f"- Original evidence: BOM row {part['bom_row']}",
    ]

    if accepted_material is not None:
        lines.append(
            f"- Accepted correction applied: material changed from "
            f"**{original_material}** to **{accepted_material}**"
        )

    return "\n".join(lines)

def answer_multi_document_query(parts, query):
    q = query.lower().strip()

    # Shared material query:
    # Example: "Which parts use Aluminium?"
    if q.startswith("which parts use "):
        material = query[len("Which parts use "):].strip().rstrip("?")

        matches = [
            part for part in parts
            if part.get("material")
            and material.lower() in str(part["material"]).lower()
        ]

        if not matches:
            return (
                f"I could not find BOM parts with recorded material matching "
                f"**{material}**."
            )

        lines = [
            f"I found **{len(matches)}** BOM parts with recorded material matching "
            f"**{material}**:",
            ""
        ]

        for part in matches[:15]:
            lines.append(
                f"- **{part['name']}** — subsystem: "
                f"{part.get('subsystem') or 'unknown'}, "
                f"BOM row {part.get('bom_row')}"
            )

        if len(matches) > 15:
            lines.append("")
            lines.append(
                f"_Showing the first 15 of {len(matches)} matching BOM records._"
            )

        lines.append("")
        lines.append(
            "_Material values are recorded BOM snapshot evidence, "
            "not guaranteed current manufacturing truth._"
        )

        return "\n".join(lines)

    # Subsystem supplier query:
    # Example: "Which parts in the Recoater subsystem have suppliers?"
    if (
        q.startswith("which parts in the ")
        and " subsystem have suppliers" in q
    ):
        prefix = "which parts in the "
        suffix = " subsystem have suppliers"

        subsystem = q[
            len(prefix):
            q.index(suffix)
        ].strip()

        matches = [
            part for part in parts
            if part.get("subsystem")
            and part["subsystem"].lower() == subsystem
            and part.get("supplier")
        ]

        if not matches:
            return (
                f"I could not find parts in the **{subsystem}** subsystem "
                f"with a recorded supplier."
            )

        lines = [
            f"Recorded suppliers for parts in the **{subsystem}** subsystem:",
            ""
        ]

        for part in matches[:15]:
            lines.append(
                f"- **{part['name']}** — supplier: "
                f"**{part['supplier']}** — BOM row {part.get('bom_row')}"
            )

        if len(matches) > 15:
            lines.append("")
            lines.append(
                f"_Showing the first 15 of {len(matches)} matching BOM records._"
            )

        lines.append("")
        lines.append(
            "_Supplier values come from the pinned BOM snapshot and may be stale; "
            "they are not current availability claims._"
        )

        return "\n".join(lines)

    # Subsystem cost query:
    # Example: "What are the recorded costs for parts in the Recoater subsystem?"
    if (
        q.startswith("what are the recorded costs for parts in the ")
        and q.endswith(" subsystem?")
    ):
        prefix = "what are the recorded costs for parts in the "
        suffix = " subsystem?"

        subsystem = q[
            len(prefix):
            len(q) - len(suffix)
        ].strip()

        matches = [
            part for part in parts
            if part.get("subsystem")
            and part["subsystem"].lower() == subsystem
            and part.get("cost") not in (None, "", "nan")
        ]

        if not matches:
            return (
                f"I could not find recorded cost values for parts in the "
                f"**{subsystem}** subsystem."
            )

        lines = [
            f"Recorded BOM costs for parts in the **{subsystem}** subsystem:",
            ""
        ]

        for part in matches[:15]:
            lines.append(
                f"- **{part['name']}** — recorded cost: "
                f"**{part['cost']}** — BOM row {part.get('bom_row')}"
            )

        if len(matches) > 15:
            lines.append("")
            lines.append(
                f"_Showing the first 15 of {len(matches)} matching BOM records._"
            )

        lines.append("")
        lines.append(
            "_These costs are historical values from the pinned BOM snapshot, "
            "not current prices._"
        )

        return "\n".join(lines)

    return None

def find_best_part(parts, drawings, query):
    query_lower = query.lower().strip()

    # 1. Try BOM-backed parts first.
    exact_or_contains = [
        part
        for part in parts
        if part["name"].lower() in query_lower
        or query_lower in part["name"].lower()
    ]

    if exact_or_contains:
        return {
            "kind": "part",
            "record": exact_or_contains[0],
        }

    # 2. Fall back to curated drawing titles.
    for drawing in drawings:
        title = drawing.get("title")

        if title and title.lower() in query_lower:
            return {
                "kind": "drawing",
                "record": drawing,
            }

    return None
def parse_material_correction(prompt, parts):
    pattern = re.compile(
        r"(?:change|correct|update)\s+(?:the\s+)?material\s+(?:of|for)\s+(.+?)\s+to\s+(.+)",
        re.IGNORECASE,
    )

    match = pattern.search(prompt)

    if not match:
        return None

    part_text = match.group(1).strip()
    proposed_material = match.group(2).strip().rstrip(".")

    matched_part = None

    for part in parts:
        if part["name"].lower() == part_text.lower():
            matched_part = part
            break

    if matched_part is None:
        return None

    return {
        "part": matched_part,
        "proposed_material": proposed_material,
    }


knowledge = load_knowledge()

parts = knowledge["parts"]
drawings = knowledge["drawings"]

if "messages" not in st.session_state:
    st.session_state.messages = []

if "selected_part" not in st.session_state:
    st.session_state.selected_part = None

if "selected_drawing" not in st.session_state:
    st.session_state.selected_drawing = None


st.set_page_config(
    page_title="Project Meridian",
    page_icon="🧭",
    layout="wide",
)

st.title("Project Meridian")
st.caption("Evidence-grounded drawing intelligence for OpenLPBF v2")


left, right = st.columns([1, 1])


with left:
    st.subheader("Chat")

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input(
        "Ask about a part, e.g. 'Tell me about the Recoater mount block'"
    )

    if prompt:
        st.session_state.messages.append(
            {
                "role": "user",
                "content": prompt,
            }
        )
        correction = parse_material_correction(prompt, parts)
        if correction is not None:
            part = correction["part"]
            proposed_material = correction["proposed_material"]

            proposal = create_proposal(
                part_name=part["name"],
                field="material",
                current_value=part["material"],
                proposed_value=proposed_material,
                source_ref=f"BOM row {part['bom_row']}",
            )

            response = (
                f"I created correction proposal **{proposal['id']}**.\n\n"
                f"- Part: **{part['name']}**\n"
                f"- Field: material\n"
                f"- Current source value: **{part['material']}**\n"
                f"- Proposed value: **{proposed_material}**\n\n"
                "The source evidence has not been changed. "
                "A human must accept or reject this proposal in the review panel."

            )

            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": response,
                }
            )
            st.session_state.selected_part = part
            st.session_state.selected_drawing = None
            st.rerun()
        

        multi_answer = answer_multi_document_query(parts, prompt)
        if multi_answer is not None:
            response = multi_answer
            st.session_state.selected_part = None
            st.session_state.selected_drawing = None
        else:
            result = find_best_part(parts, drawings, prompt)
            if result is None:
                response = (
                    "I could not find a supported structured match for that question. "
                    "Try naming a BOM part or one of the curated drawings."

                )
            elif result["kind"] == "part":
                part = result["record"]
                response = answer_for_part(part)
                st.session_state.selected_part = part
                st.session_state.selected_drawing = None
            elif result["kind"] == "drawing":
                drawing = result["record"]
                response = (
                    f"I found drawing **{drawing['drawing_id']} — {drawing['title']}**. "
                    "I do not have a verified BOM identity for this drawing, so I am "
                    "showing the drawing evidence without claiming that it is the same "
                    "part as a BOM record."
                )
                st.session_state.selected_part = None
                st.session_state.selected_drawing = drawing


        

        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": response,
            }
        )

        st.rerun()


with right:
    st.subheader("Drawing evidence")

    selected = st.session_state.selected_part
    selected_drawing = st.session_state.selected_drawing

    if selected is None and selected_drawing is None:
        st.info("Ask about a part in chat to inspect its drawing evidence.")

    else:
        if selected_drawing is not None:
            drawing = selected_drawing
        else:
            drawing = find_drawing_for_part(drawings, selected["name"])
        
        

        if drawing is None:
            st.info(
                "No verified drawing link is currently available "
                "for this part."
            )

        else:
            st.markdown(
                f"### {drawing['drawing_id']} — "
                f"{drawing['title']}"
            )

            st.write(
                f"**Drawing material:** "
                f"{drawing['material'] or 'Unknown'}"
            )

            st.write(
                f"**Source quality:** "
                f"{drawing['distribution']}"
            )

            st.write(
                f"**Link status:** "
                f"{drawing['match_status']}"
            )
            if drawing["match_status"] == "unverified":
                 st.warning(
                     "Identity evidence is not fully consistent. "
                     "The upstream source filename suggests 'RecoaterStagePlate', "
                     "while the drawing title says 'Recoater Linear Plate'. "
                     "A similarly named BOM row exists, so this relationship is "
                     "shown as a candidate rather than a verified identity."
                    )

            pdf_path = PROJECT_ROOT / drawing["file_path"]

            if pdf_path.exists():
                image_bytes = render_pdf_page(str(pdf_path))

                st.image(
                    image_bytes,
                    caption=f"{drawing['drawing_id']} — source drawing",
                    width="stretch",
                )
            else:
                st.error("Drawing file could not be found.")

            st.caption(
                "Drawing and BOM evidence are preserved "
                "as separate source claims."
            )

            if drawing["drawing_id"] in {"D-012", "D-025", "D-026"}:
                st.markdown("### 3D reconstruction")
                st.caption(
                    "Reconstructed from the supplied 2D drawing evidence. "
                    "This is not native CAD."
                )
                if drawing["drawing_id"] == "D-012":
                    fig = recoater_mount_block_figure()
                    limitation = (
                        "Current reconstruction represents the main "
                        "120 × 25 × 15 mm block envelope; "
                        "hole/thread details are not yet modeled."
                    )
                elif drawing["drawing_id"] == "D-026":
                    fig = build_plate_figure()
                    limitation = (
                        "Current reconstruction represents the main circular "
                        "plate envelope; the three through-hole features are "
                        "not yet modeled."
                    )
                else:
                    fig = bygge_base_ring_figure()
                    limitation = (
                        "Current reconstruction represents the ring envelope; "
                        "the eight countersunk holes are not yet modeled."
                    )
                st.plotly_chart(
                    fig,
                    width="stretch",
                )
                st.caption(limitation)
st.divider()

st.subheader("Correction review")

pending = get_pending_proposals()

if not pending:
    st.info("No pending correction proposals.")

else:
    for proposal in pending:
        with st.container(border=True):
            st.markdown(
                f"### {proposal['id']} — {proposal['part_name']}"
            )

            st.write(
                f"**Field:** {proposal['field']}"
            )

            st.write(
                f"**Original source value:** "
                f"{proposal['current_value']}"
            )

            st.write(
                f"**Proposed value:** "
                f"{proposal['proposed_value']}"
            )

            st.write(
                f"**Original evidence:** "
                f"{proposal['source_ref']}"
            )

            col_accept, col_reject = st.columns(2)

            with col_accept:
                if st.button(
                    "Accept",
                    key=f"accept-{proposal['id']}",
                    type="primary",
                ):
                    accept_proposal(proposal["id"])
                    st.success("Correction accepted.")
                    st.rerun()

            with col_reject:
                if st.button(
                    "Reject",
                    key=f"reject-{proposal['id']}",
                ):
                    reject_proposal(proposal["id"])
                    st.warning("Correction rejected.")
                    st.rerun()
with st.expander("Correction history"):
    history = get_history()

    st.markdown("#### Accepted")
    if history["accepted"]:
        st.json(history["accepted"])
    else:
        st.write("None")

    st.markdown("#### Rejected")
    if history["rejected"]:
        st.json(history["rejected"])
    else:
        st.write("None")
                     
                         

    
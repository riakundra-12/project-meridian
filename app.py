import json
import os
from pathlib import Path

import streamlit as st
import pymupdf
from dotenv import load_dotenv
from src.visualization.models_3d import (
    recoater_mount_block_figure,
    build_plate_figure,
    bygge_base_ring_figure,
)
from src.visualization.cadquery_mesh import extracted_drawing_figure

import re

from src.corrections.store import (
    create_proposal,
    get_pending_proposals,
    accept_proposal,
    reject_proposal,
    get_history,
)
from src.agent.chat_agent import run_turn
from src.agent.provider import build_provider

load_dotenv()


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

AGENT_PROVIDER = os.environ.get("AGENT_PROVIDER", "gemini")
try:
    provider = build_provider(AGENT_PROVIDER)
    provider_error = None
except Exception as e:
    provider = None
    provider_error = str(e)

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
        

        else:
            agent_result = None
            if provider is None:
                response = f"⚠️ Chat agent isn't configured: {provider_error}"
            else:
                try:
                    with st.spinner("Thinking — calling tools..."):
                        agent_result = run_turn(provider, prompt)
                except Exception as e:
                    response = f"⚠️ Chat agent call failed: {e}"

            if agent_result is not None:
                response = agent_result.rendered_text
                if agent_result.dropped_count:
                    plural = "s" if agent_result.dropped_count != 1 else ""
                    response += (
                        f"\n\n_[{agent_result.dropped_count} unverified "
                        f"claim{plural} dropped]_"
                    )

                if agent_result.referenced_drawing_ids:
                    drawing_id = agent_result.referenced_drawing_ids[0]
                    st.session_state.selected_drawing = next(
                        (d for d in drawings if d["drawing_id"] == drawing_id), None
                    )
                    st.session_state.selected_part = None
                elif agent_result.referenced_part_ids:
                    part_name = agent_result.referenced_part_ids[0]
                    st.session_state.selected_part = next(
                        (p for p in parts if p["name"] == part_name), None
                    )
                    st.session_state.selected_drawing = None
                else:
                    st.session_state.selected_part = None
                    st.session_state.selected_drawing = None


        

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
            else:
                extracted_fig = extracted_drawing_figure(drawing["drawing_id"])
                if extracted_fig is not None:
                    st.markdown("### 3D reconstruction")
                    st.caption(
                        "Reconstructed from the supplied 2D drawing evidence. "
                        "This is not native CAD."
                    )
                    st.plotly_chart(extracted_fig, width="stretch")
                    st.caption(
                        "Generated from B5's vision-extracted dimensions via "
                        "CadQuery, not hand-built — hover the shape for the "
                        "extracted dimensions and their confidence tags."
                    )
st.divider()

def _proposal_origin_label(source_ref: str) -> str:
    """Inferred from source_ref's prefix, no schema change needed --
    'drawing:<id>' only ever comes from B5's ingestion auto-filing a
    BOM-vs-drawing conflict; every other source_ref comes from a user's
    chat-proposed correction."""
    if source_ref.startswith("drawing:"):
        return "System-proposed (ingestion)"
    return "User-proposed"


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

            st.caption(_proposal_origin_label(proposal["source_ref"]))

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
def _render_history_card(item: dict) -> None:
    with st.container(border=True):
        st.markdown(f"**{item['id']} — {item['part_name']}**")
        st.caption(
            f"{_proposal_origin_label(item['source_ref'])} · "
            f"reviewed {item.get('reviewed_at', 'unknown time')}"
        )
        st.write(
            f"{item['field']}: **{item['current_value']}** → "
            f"**{item['proposed_value']}** _[{item['source_ref']}]_"
        )


with st.expander("Correction history"):
    history = get_history()

    st.markdown("#### Accepted")
    if history["accepted"]:
        for item in history["accepted"]:
            _render_history_card(item)
    else:
        st.write("None")

    st.markdown("#### Rejected")
    if history["rejected"]:
        for item in history["rejected"]:
            _render_history_card(item)
    else:
        st.write("None")
                     
                         

    
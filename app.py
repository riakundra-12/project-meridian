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
    revert_correction,
    get_history,
)
from src.agent.chat_agent import run_turn_with_failover
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
    """Confirmed real (AGY audit, 2026-10-11): restricting this to
    match_status == "verified" left only 2 of 30 drawings reachable by
    asking about a part by name -- D-012 and D-026 -- breaking requirement
    #3 for the other 190 BOM parts, including the 2 'unverified' drawings
    that already have working warning-banner UI (render_drawing_evidence)
    sitting unreachable behind this filter. 'unmatched'/no-link drawings
    still correctly return None below -- there's genuinely no candidate
    link to show for those, that's not a bug."""
    for drawing in drawings:
        bom_match = drawing.get("bom_match")

        if (
            bom_match
            and bom_match.lower() == part_name.lower()
            and drawing.get("match_status") in ("verified", "unverified")
        ):
            return drawing

    return None


def render_drawing_evidence(container, selected, selected_drawing):
    """Staged rendering: text/BOM fields -> 2D drawing -> 3D reconstruction,
    each with its own spinner, so the user sees progress instead of nothing
    until the whole turn finishes. Called twice per chat turn by design:
    once immediately after the agent answers (inside the chat-handling
    block, before st.rerun() -- for instant feedback) and once normally on
    the next rerun (reading session_state -- for persistence on reload).
    st.rerun() always cuts the first call's script execution short right
    after it runs, so there's no double-render in a single pass.
    """
    with container:
        st.subheader("Drawing evidence")

        if selected is None and selected_drawing is None:
            st.info("Ask about a part in chat to inspect its drawing evidence.")
            return

        with st.spinner("Loading drawing evidence..."):
            if selected_drawing is not None:
                drawing = selected_drawing
            else:
                drawing = find_drawing_for_part(drawings, selected["name"])

        if drawing is None:
            st.info(
                "No verified drawing link is currently available "
                "for this part."
            )
            return

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

        with st.spinner("Rendering 2D drawing..."):
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
            with st.spinner("Generating 3D reconstruction..."):
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
            with st.spinner("Generating 3D reconstruction..."):
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


def _current_overlaid_value(part_name, field, raw_value):
    """Confirmed real gap (AGY audit, 2026-10-11): this chat-side correction
    path read the raw BOM value directly, so proposing a SECOND correction
    on a part that already has an accepted one would record the ORIGINAL
    pre-correction value as current_value in the new proposal's audit
    trail -- stale data baked into a new record. tools.py's
    _apply_corrections_overlay does the equivalent for the chat agent's
    reads; this is the same resolution for this one call site, not a new
    mechanism."""
    for item in get_history().get("accepted", []):
        if item.get("part_name", "").lower() == part_name.lower() and item.get("field") == field:
            return item["proposed_value"]
    return raw_value


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


@st.cache_resource
def _get_provider(provider_name: str):
    # Streamlit reruns the whole script on every interaction -- without
    # this cache, a fresh GeminiProvider/GroqProvider (and its underlying
    # API client) was being rebuilt on every single chat message. Safe to
    # cache: a provider's only mutable state (_last_model_content, for
    # Gemini) is set then read within one run_turn() call before the next
    # one starts, never shared across concurrent turns in Streamlit's
    # single-threaded-per-session model.
    return build_provider(provider_name)


try:
    provider = _get_provider(AGENT_PROVIDER)
    provider_error = None
except Exception as e:
    provider = None
    provider_error = str(e)

# SUP-001: Gemini's real, confirmed 20-req/day-per-model ceiling has no
# runtime recovery otherwise -- AGENT_PROVIDER is read once at process
# startup. Only wire a fallback when the primary is actually gemini; an
# explicit AGENT_PROVIDER=groq/mock/hf keeps meaning exactly that provider,
# no silent substitution.
fallback_provider = None
if AGENT_PROVIDER == "gemini":
    try:
        fallback_provider = _get_provider("groq")
    except Exception:
        fallback_provider = None  # no GROQ_API_KEY configured -- fine, just no safety net

if "messages" not in st.session_state:
    st.session_state.messages = []

if "provider_switched" not in st.session_state:
    st.session_state.provider_switched = False

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

            current_material = _current_overlaid_value(part["name"], "material", part["material"])
            proposal = create_proposal(
                part_name=part["name"],
                field="material",
                current_value=current_material,
                proposed_value=proposed_material,
                source_ref=f"BOM row {part['bom_row']}",
            )

            response = (
                f"I created correction proposal **{proposal['id']}**.\n\n"
                f"- Part: **{part['name']}**\n"
                f"- Field: material\n"
                f"- Current source value: **{current_material}**\n"
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

            with st.chat_message("assistant"):
                st.markdown(response)
            render_drawing_evidence(right, part, None)

            st.rerun()


        else:
            agent_result = None
            if provider is None:
                response = f"⚠️ Chat agent isn't configured: {provider_error}"
            else:
                try:
                    with st.spinner("Thinking — calling tools..."):
                        agent_result, switched = run_turn_with_failover(
                            provider, fallback_provider, prompt,
                            already_switched=st.session_state.provider_switched,
                        )
                    if switched and not st.session_state.provider_switched:
                        st.warning(
                            "Gemini's daily quota was reached — switched to "
                            "Groq for this and future questions this session."
                        )
                    st.session_state.provider_switched = switched
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

        with st.chat_message("assistant"):
            st.markdown(response)
        render_drawing_evidence(
            right, st.session_state.selected_part, st.session_state.selected_drawing
        )

        st.rerun()


render_drawing_evidence(
    right, st.session_state.selected_part, st.session_state.selected_drawing
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
def _render_history_card(item: dict, allow_revert: bool = False) -> None:
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
        if item.get("reverted_at"):
            st.caption(f"Reverted {item['reverted_at']}")
        if allow_revert and st.button(
            "Revert",
            key=f"revert-{item['id']}",
            help="Moves this back to rejected — e.g. if the acceptance "
                 "is later found to rest on a bad match.",
        ):
            revert_correction(item["id"])
            st.warning(f"{item['id']} reverted.")
            st.rerun()


with st.expander("Correction history"):
    history = get_history()

    st.markdown("#### Accepted")
    if history["accepted"]:
        for item in history["accepted"]:
            _render_history_card(item, allow_revert=True)
    else:
        st.write("None")

    st.markdown("#### Rejected")
    if history["rejected"]:
        for item in history["rejected"]:
            _render_history_card(item)
    else:
        st.write("None")
                     
                         

    
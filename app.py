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
        _section_header("Drawing evidence")

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

        status = drawing['match_status'] or 'unmatched'
        st.markdown(
            f'**Link status:** <span class="status-badge status-{status}">{status}</span>',
            unsafe_allow_html=True,
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

# Visual design pass (2026-10-11) -- was zero custom CSS / no .streamlit/
# config.toml theme before this, confirmed by searching the repo. Targets
# STABLE data-testid selectors, not Streamlit's hashed emotion-cache
# classes (those rotate across Streamlit versions -- confirmed unstable
# while inspecting the live DOM earlier this session).
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    [data-testid="stChatMessage"] {
        border-radius: 14px;
        border: 1px solid rgba(32, 35, 31, 0.08);
        padding: 0.3rem 0.6rem;
        margin-bottom: 0.4rem;
    }

    [data-testid="stHorizontalBlock"] { gap: 0.4rem !important; }

    [data-testid="stAlertContainer"] { border-radius: 10px; }

    [data-testid="stButton"] button { border-radius: 999px !important; }

    h2, h3 { letter-spacing: 0.01em; }

    .section-rule {
        border: none;
        border-top: 2px solid #C2572F;
        width: 2.2rem;
        margin: 0.1rem 0 0.9rem 0;
    }

    .sources-label {
        font-size: 0.72rem;
        font-weight: 600;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: #8a8577;
        margin: 0.4rem 0 0.3rem 0.1rem;
    }

    .source-chip {
        display: inline-block;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.78rem;
        padding: 0.2rem 0.65rem;
        border-radius: 999px;
        margin: 0 0.3rem 0.3rem 0;
        border: 1px solid transparent;
    }
    .source-chip-bom { background: #EEEAE2; color: #4A4538; border-color: #DCD5C6; }
    .source-chip-drawing { background: #F6E3DA; color: #9A3F1C; border-color: #EBC4AF; }
    .source-chip-correction { background: #E3EDE3; color: #2F5C33; border-color: #C6DCC6; }

    .status-badge {
        display: inline-block;
        font-size: 0.72rem;
        font-weight: 600;
        padding: 0.15rem 0.6rem;
        border-radius: 999px;
    }
    .status-verified { background: #E3EDE3; color: #2F5C33; }
    .status-unverified { background: #FBF0D9; color: #8A5A00; }
    .status-unmatched { background: #EEEAE2; color: #6B6758; }
    .origin-user { background: #F6E3DA; color: #9A3F1C; }
    .origin-system { background: #E3EDE3; color: #2F5C33; }
    </style>
    """,
    unsafe_allow_html=True,
)


def _section_header(text: str) -> None:
    st.markdown(
        f'<h3 style="margin-bottom:0.2rem;">{text}</h3><hr class="section-rule">',
        unsafe_allow_html=True,
    )


_SOURCE_TYPE_META = {
    "bom": ("📄", "BOM", "bom"),
    "manifest": ("📐", "Drawing", "drawing"),
    "curated": ("📐", "Drawing (curated)", "drawing"),
    "extracted": ("📐", "Drawing (extracted)", "drawing"),
    "correction": ("✏️", "Correction", "correction"),
}


def _classify_source(source_ref: str):
    for prefix in ("correction", "curated", "extracted", "manifest"):
        if source_ref.startswith(f"{prefix}:"):
            return _SOURCE_TYPE_META[prefix]
    return _SOURCE_TYPE_META["bom"]  # "BOM row N" reads fine as-is


def _chip_label(source_ref: str, kind: str) -> str:
    """Short enough to fit a pill button without Streamlit's default
    truncation (confirmed live: 6-wide st.columns + a full source_ref like
    'BOM row 19' clipped to 'BO…'). Full source_ref is still available via
    the button's hover tooltip (see _render_sources)."""
    if kind == "bom" and source_ref.lower().startswith("bom row "):
        return f"Row {source_ref[8:]}"
    if ":" in source_ref:
        return source_ref.split(":", 1)[-1]
    return source_ref


def _render_sources(claims: list, msg_key: str) -> None:
    """The "relevant documents" section: one deduped chip per unique
    source_ref a message's validated claims actually cite. Reads directly
    from TurnResult.validated_claims (see chat_agent.py) -- never
    re-parses the rendered answer text, so this can never show a source
    the validator didn't actually check. Drawing/BOM-entity chips are
    real buttons that jump the evidence panel straight to that source;
    correction-type chips have no equivalent detail view today, so they
    render as plain static chips."""
    if not claims:
        return

    seen = {}
    for c in claims:
        seen.setdefault(c["source_ref"], c)  # first claim naming this source wins for dedup

    st.markdown('<div class="sources-label">Relevant documents</div>', unsafe_allow_html=True)
    shown = list(seen.items())[:6]
    # Fixed 3-wide rows, not one row sized to however many sources exist --
    # confirmed live that >3 equal-width columns in this panel truncates
    # button text no matter how short the label is.
    COLS_PER_ROW = 3
    for row_start in range(0, len(shown), COLS_PER_ROW):
        row = shown[row_start:row_start + COLS_PER_ROW]
        cols = st.columns(COLS_PER_ROW)
        for col, (source_ref, claim) in zip(cols, row):
            icon, label, kind = _classify_source(source_ref)
            chip_text = f"{icon} {_chip_label(source_ref, kind)}"
            entity_id = claim["entity_id"]

            with col:
                if kind == "drawing":
                    if st.button(chip_text, key=f"src-{msg_key}-{source_ref}", help=f"{label}: {source_ref}"):
                        st.session_state.selected_drawing = next(
                            (d for d in drawings if d["drawing_id"] == entity_id), None
                        )
                        st.session_state.selected_part = None
                        st.rerun()
                elif kind == "bom":
                    if st.button(chip_text, key=f"src-{msg_key}-{source_ref}", help=f"{label}: {source_ref}"):
                        st.session_state.selected_part = next(
                            (p for p in parts if p["name"] == entity_id), None
                        )
                        st.session_state.selected_drawing = None
                        st.rerun()
                else:
                    st.markdown(
                        f'<span class="source-chip source-chip-{kind}" title="{source_ref}">{chip_text}</span>',
                        unsafe_allow_html=True,
                )
    if len(seen) > 6:
        st.caption(f"+ {len(seen) - 6} more source{'s' if len(seen) - 6 != 1 else ''}")


st.title("Project Meridian")
st.caption("Evidence-grounded drawing intelligence for OpenLPBF v2")


left, right = st.columns([1, 1])


with left:
    _section_header("Chat")

    for idx, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            _render_sources(message.get("claims", []), msg_key=f"hist-{idx}")

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
                    "claims": [],
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
                "claims": agent_result.validated_claims if agent_result is not None else [],
            }
        )

        with st.chat_message("assistant"):
            st.markdown(response)
            _render_sources(
                agent_result.validated_claims if agent_result is not None else [],
                msg_key=f"hist-{len(st.session_state.messages) - 1}",
            )
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


def _origin_badge_html(source_ref: str) -> str:
    is_system = source_ref.startswith("drawing:")
    css_class = "origin-system" if is_system else "origin-user"
    label = _proposal_origin_label(source_ref)
    return f'<span class="status-badge {css_class}">{label}</span>'


_section_header("Correction review")

pending = get_pending_proposals()

if not pending:
    st.info("No pending correction proposals.")

else:
    for proposal in pending:
        with st.container(border=True):
            st.markdown(
                f"### {proposal['id']} — {proposal['part_name']}"
            )

            st.markdown(_origin_badge_html(proposal["source_ref"]), unsafe_allow_html=True)

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
        st.markdown(
            f"{_origin_badge_html(item['source_ref'])} "
            f"<span style='color:#8a8577;font-size:0.82rem;'> · reviewed "
            f"{item.get('reviewed_at', 'unknown time')}</span>",
            unsafe_allow_html=True,
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
                     
                         

    
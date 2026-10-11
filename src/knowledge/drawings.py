from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class DrawingRecord:
    drawing_id: str
    subsystem: str
    source_path: str
    file_path: str
    distribution: str
    pages: int
    title: Optional[str] = None
    material: Optional[str] = None
    bom_match: Optional[str] = None
    match_status: Optional[str] = None
    # "human" (CURATED_DRAWINGS) or "auto_extraction" (B5 vision pipeline).
    # Without this, D-012 (genuinely human-reviewed) and D-013 (never
    # looked at by a person) were structurally identical records -- the
    # chat agent's citations tagged both "curated:", falsely implying
    # human review for raw extraction output (confirmed real gap, AGY
    # audit 2026-10-11).
    curation_source: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)
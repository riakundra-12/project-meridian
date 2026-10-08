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

    def to_dict(self) -> dict:
        return asdict(self)
from dataclasses import dataclass, asdict
from typing import Any, Optional


@dataclass
class Evidence:
    source_type: str
    source_ref: str
    field: str
    value: Any
    confidence: float = 1.0
    note: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PartRecord:
    name: str
    subsystem: str
    part_type: Optional[str]
    material: Optional[str]
    supplier: Optional[str]
    amount: Optional[float]
    cost: Optional[str]
    bom_row: int
    evidence: list[Evidence]

    def to_dict(self) -> dict:
        result = asdict(self)
        result["evidence"] = [e.to_dict() for e in self.evidence]
        return result
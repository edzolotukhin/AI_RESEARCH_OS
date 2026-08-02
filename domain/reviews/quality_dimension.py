from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class QualityDimensionStatus(str, Enum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


class QualityDimensionName(str, Enum):
    BRIEF_COVERAGE = "brief_coverage"
    RESEARCH_QUESTION_COVERAGE = "research_question_coverage"
    EVIDENCE_SUPPORT = "evidence_support"
    CITATION_COMPLETENESS = "citation_completeness"
    ANALYTICAL_CONSISTENCY = "analytical_consistency"
    CONTRADICTION_HANDLING = "contradiction_handling"
    LIMITATIONS_COMPLETENESS = "limitations_completeness"
    DELIVERABLE_COMPLIANCE = "deliverable_compliance"


@dataclass(frozen=True)
class QualityDimension:
    name: QualityDimensionName
    status: QualityDimensionStatus
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name.value,
            "status": self.status.value,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> QualityDimension:
        return cls(
            name=QualityDimensionName(str(payload["name"])),
            status=QualityDimensionStatus(str(payload["status"])),
            message=str(payload.get("message", "")),
        )

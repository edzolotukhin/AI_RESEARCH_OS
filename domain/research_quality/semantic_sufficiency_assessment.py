from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.common.exceptions import ValidationError
from domain.research_quality._helpers import (
    tuple_of_enum,
    tuple_of_str,
    validate_unit_score,
)
from domain.research_quality.gap_type import GapType
from domain.research_quality.sufficiency_status import SufficiencyStatus


@dataclass(frozen=True)
class SemanticSufficiencyAssessment:
    """Semantic sufficiency judgment scoped to one existing InformationNeed."""

    status: SufficiencyStatus
    missing_aspects: tuple[str, ...] = ()
    gap_types: tuple[GapType, ...] = ()
    search_directives: tuple[str, ...] = ()
    confidence: float | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "missing_aspects", tuple_of_str(self.missing_aspects))
        object.__setattr__(
            self,
            "gap_types",
            tuple_of_enum(GapType, self.gap_types),
        )
        object.__setattr__(
            self,
            "search_directives",
            tuple_of_str(self.search_directives),
        )
        object.__setattr__(self, "reason", str(self.reason))
        validate_unit_score("confidence", self.confidence)

        if self.status == SufficiencyStatus.SUFFICIENT:
            blocking = [
                gap_type.value
                for gap_type in self.gap_types
                if gap_type == GapType.NO_EVIDENCE
            ]
            if blocking:
                raise ValidationError(
                    "SUFFICIENT semantic assessment must not include NO_EVIDENCE",
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "missing_aspects": list(self.missing_aspects),
            "gap_types": [gap_type.value for gap_type in self.gap_types],
            "search_directives": list(self.search_directives),
            "confidence": self.confidence,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SemanticSufficiencyAssessment:
        return cls(
            status=SufficiencyStatus(str(payload["status"])),
            missing_aspects=tuple_of_str(payload.get("missing_aspects")),
            gap_types=tuple_of_enum(GapType, payload.get("gap_types")),
            search_directives=tuple_of_str(payload.get("search_directives")),
            confidence=(
                float(payload["confidence"])
                if payload.get("confidence") is not None
                else None
            ),
            reason=str(payload.get("reason", "")),
        )

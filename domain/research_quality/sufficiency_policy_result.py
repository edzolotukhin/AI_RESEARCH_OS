from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.research_quality._helpers import tuple_of_enum, validate_non_negative_count, validate_unit_score
from domain.research_quality.gap_type import BLOCKING_GAP_TYPES, GapType
from domain.research_quality.policy_sufficiency_status import (
    derive_policy_sufficiency_status,
)
from domain.research_quality.sufficiency_status import SufficiencyStatus


@dataclass(frozen=True)
class SufficiencyPolicyResult:
    """Deterministic policy foundation for one InformationNeed."""

    coverage: float
    gap_types: tuple[GapType, ...] = ()
    evidence_count: int = 0

    def __post_init__(self) -> None:
        validate_unit_score("coverage", self.coverage)
        validate_non_negative_count("evidence_count", self.evidence_count)
        object.__setattr__(
            self,
            "gap_types",
            tuple_of_enum(GapType, self.gap_types),
        )

    @property
    def status(self) -> SufficiencyStatus:
        return derive_policy_sufficiency_status(
            coverage=self.coverage,
            gap_types=self.gap_types,
            evidence_count=self.evidence_count,
        )

    @property
    def blocking(self) -> bool:
        return any(gap_type in BLOCKING_GAP_TYPES for gap_type in self.gap_types)

    def to_dict(self) -> dict[str, Any]:
        return {
            "coverage": self.coverage,
            "gap_types": [gap_type.value for gap_type in self.gap_types],
            "evidence_count": self.evidence_count,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SufficiencyPolicyResult:
        return cls(
            coverage=float(payload["coverage"]),
            gap_types=tuple_of_enum(GapType, payload.get("gap_types")),
            evidence_count=int(payload.get("evidence_count", 0)),
        )

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.common.exceptions import ValidationError
from domain.research_quality._helpers import (
    tuple_of_enum,
    tuple_of_str,
    validate_non_negative_count,
    validate_unit_score,
)
from domain.research_quality.gap_type import GapType


@dataclass(frozen=True)
class DeterministicSufficiencySignals:
    """Objective, policy-free sufficiency facts for one InformationNeed."""

    information_need_id: str
    research_question_id: str
    evidence_count: int = 0
    independent_source_count: int = 0
    evidence_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    freshness_available: bool = False
    freshness_score: float | None = None
    source_quality_available: bool = False
    source_quality_score: float | None = None
    source_diversity_available: bool = False
    source_diversity_score: float | None = None
    quantitative_evidence_present: bool | None = None
    duplicate_evidence_count: int = 0
    contradictions: tuple[str, ...] = ()
    deterministic_gap_types: tuple[GapType, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "information_need_id",
            str(self.information_need_id).strip(),
        )
        object.__setattr__(
            self,
            "research_question_id",
            str(self.research_question_id).strip(),
        )
        object.__setattr__(self, "evidence_ids", tuple_of_str(self.evidence_ids))
        object.__setattr__(self, "source_ids", tuple_of_str(self.source_ids))
        object.__setattr__(self, "contradictions", tuple_of_str(self.contradictions))
        object.__setattr__(
            self,
            "deterministic_gap_types",
            tuple_of_enum(GapType, self.deterministic_gap_types),
        )
        object.__setattr__(self, "warnings", tuple_of_str(self.warnings))

        if not self.information_need_id:
            raise ValidationError("information_need_id must not be empty")
        if not self.research_question_id:
            raise ValidationError("research_question_id must not be empty")

        validate_non_negative_count("evidence_count", self.evidence_count)
        validate_non_negative_count(
            "independent_source_count",
            self.independent_source_count,
        )
        validate_non_negative_count(
            "duplicate_evidence_count",
            self.duplicate_evidence_count,
        )
        validate_unit_score("freshness_score", self.freshness_score)
        validate_unit_score("source_quality_score", self.source_quality_score)
        validate_unit_score("source_diversity_score", self.source_diversity_score)

        if self.freshness_available and self.freshness_score is None:
            raise ValidationError(
                "freshness_available=True requires freshness_score",
            )
        if not self.freshness_available and self.freshness_score is not None:
            raise ValidationError(
                "freshness_score requires freshness_available=True",
            )
        if self.source_quality_available and self.source_quality_score is None:
            raise ValidationError(
                "source_quality_available=True requires source_quality_score",
            )
        if not self.source_quality_available and self.source_quality_score is not None:
            raise ValidationError(
                "source_quality_score requires source_quality_available=True",
            )
        if self.source_diversity_available and self.source_diversity_score is None:
            raise ValidationError(
                "source_diversity_available=True requires source_diversity_score",
            )
        if not self.source_diversity_available and self.source_diversity_score is not None:
            raise ValidationError(
                "source_diversity_score requires source_diversity_available=True",
            )

        if self.evidence_count == 0 and GapType.NO_EVIDENCE not in self.deterministic_gap_types:
            if self.deterministic_gap_types:
                raise ValidationError(
                    "evidence_count=0 requires deterministic_gap_types to include "
                    "NO_EVIDENCE when gaps are present",
                )
        if self.evidence_count > 0 and GapType.NO_EVIDENCE in self.deterministic_gap_types:
            raise ValidationError(
                "NO_EVIDENCE gap is incompatible with evidence_count > 0",
            )

        if self.independent_source_count > self.evidence_count:
            raise ValidationError(
                "independent_source_count cannot exceed evidence_count",
            )
        if len(self.source_ids) != self.independent_source_count:
            raise ValidationError(
                "source_ids length must match independent_source_count",
            )
        if len(self.evidence_ids) != self.evidence_count:
            raise ValidationError("evidence_ids length must match evidence_count")

    def to_dict(self) -> dict[str, Any]:
        return {
            "information_need_id": self.information_need_id,
            "research_question_id": self.research_question_id,
            "evidence_count": self.evidence_count,
            "independent_source_count": self.independent_source_count,
            "evidence_ids": list(self.evidence_ids),
            "source_ids": list(self.source_ids),
            "freshness_available": self.freshness_available,
            "freshness_score": self.freshness_score,
            "source_quality_available": self.source_quality_available,
            "source_quality_score": self.source_quality_score,
            "source_diversity_available": self.source_diversity_available,
            "source_diversity_score": self.source_diversity_score,
            "quantitative_evidence_present": self.quantitative_evidence_present,
            "duplicate_evidence_count": self.duplicate_evidence_count,
            "contradictions": list(self.contradictions),
            "deterministic_gap_types": [
                gap_type.value for gap_type in self.deterministic_gap_types
            ],
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DeterministicSufficiencySignals:
        return cls(
            information_need_id=str(payload["information_need_id"]),
            research_question_id=str(payload["research_question_id"]),
            evidence_count=int(payload.get("evidence_count", 0)),
            independent_source_count=int(payload.get("independent_source_count", 0)),
            evidence_ids=tuple_of_str(payload.get("evidence_ids")),
            source_ids=tuple_of_str(payload.get("source_ids")),
            freshness_available=bool(payload.get("freshness_available", False)),
            freshness_score=(
                float(payload["freshness_score"])
                if payload.get("freshness_score") is not None
                else None
            ),
            source_quality_available=bool(
                payload.get("source_quality_available", False),
            ),
            source_quality_score=(
                float(payload["source_quality_score"])
                if payload.get("source_quality_score") is not None
                else None
            ),
            source_diversity_available=bool(
                payload.get("source_diversity_available", False),
            ),
            source_diversity_score=(
                float(payload["source_diversity_score"])
                if payload.get("source_diversity_score") is not None
                else None
            ),
            quantitative_evidence_present=payload.get("quantitative_evidence_present"),
            duplicate_evidence_count=int(payload.get("duplicate_evidence_count", 0)),
            contradictions=tuple_of_str(payload.get("contradictions")),
            deterministic_gap_types=tuple_of_enum(
                GapType,
                payload.get("deterministic_gap_types"),
            ),
            warnings=tuple_of_str(payload.get("warnings")),
        )

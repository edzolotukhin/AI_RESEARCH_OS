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
from domain.research_quality.gap_type import BLOCKING_GAP_TYPES, GapType
from domain.research_quality.sufficiency_status import SufficiencyStatus

QUALITY_CONTRACT_EXPLICIT = "explicit_expectation"
QUALITY_CONTRACT_LEGACY = "legacy_need"
_ALLOWED_QUALITY_CONTRACT_MODES = frozenset(
    ("", QUALITY_CONTRACT_EXPLICIT, QUALITY_CONTRACT_LEGACY),
)


@dataclass(frozen=True)
class InformationNeedAssessment:
    """Run-scoped sufficiency assessment for one InformationNeed."""

    information_need_id: str
    research_question_id: str
    status: SufficiencyStatus
    evidence_count: int = 0
    independent_source_count: int = 0
    source_quality: float | None = None
    freshness: float | None = None
    source_diversity: float | None = None
    quantitative_evidence_present: bool | None = None
    contradictions: tuple[str, ...] = ()
    missing_aspects: tuple[str, ...] = ()
    gap_types: tuple[GapType, ...] = ()
    search_directives: tuple[str, ...] = ()
    confidence: float | None = None
    reason: str = ""
    quality_contract_mode: str = ""
    required_aspect_ids: tuple[str, ...] = ()
    assessment_current: bool = True
    assessment_evidence_fingerprint: str = ""
    terminal_evidence_fingerprint: str = ""
    terminal_evidence_count: int | None = None

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
        object.__setattr__(self, "contradictions", tuple_of_str(self.contradictions))
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
        object.__setattr__(
            self,
            "quality_contract_mode",
            str(self.quality_contract_mode).strip(),
        )
        object.__setattr__(
            self,
            "required_aspect_ids",
            tuple_of_str(self.required_aspect_ids),
        )
        object.__setattr__(
            self,
            "assessment_evidence_fingerprint",
            str(self.assessment_evidence_fingerprint).strip(),
        )
        object.__setattr__(
            self,
            "terminal_evidence_fingerprint",
            str(self.terminal_evidence_fingerprint).strip(),
        )

        if not self.information_need_id:
            raise ValidationError("information_need_id must not be empty")
        if not self.research_question_id:
            raise ValidationError("research_question_id must not be empty")

        validate_non_negative_count("evidence_count", self.evidence_count)
        validate_non_negative_count(
            "independent_source_count",
            self.independent_source_count,
        )
        if self.terminal_evidence_count is not None:
            validate_non_negative_count(
                "terminal_evidence_count",
                self.terminal_evidence_count,
            )
        validate_unit_score("source_quality", self.source_quality)
        validate_unit_score("freshness", self.freshness)
        validate_unit_score("source_diversity", self.source_diversity)
        validate_unit_score("confidence", self.confidence)
        if self.quality_contract_mode not in _ALLOWED_QUALITY_CONTRACT_MODES:
            raise ValidationError(
                "quality_contract_mode must be empty, "
                f"{QUALITY_CONTRACT_EXPLICIT!r}, or {QUALITY_CONTRACT_LEGACY!r}"
            )

        if self.status == SufficiencyStatus.MISSING and self.evidence_count > 0:
            raise ValidationError(
                "MISSING assessments must have evidence_count == 0",
            )
        if not self.assessment_current and GapType.STALE_EVIDENCE not in self.gap_types:
            raise ValidationError(
                "non-current assessments must include stale_evidence",
            )
        if (
            self.assessment_current
            and self.assessment_evidence_fingerprint
            and self.terminal_evidence_fingerprint
            and self.assessment_evidence_fingerprint
            != self.terminal_evidence_fingerprint
        ):
            raise ValidationError(
                "current assessments require matching evidence fingerprints",
            )
        if self.status == SufficiencyStatus.SUFFICIENT:
            if self.evidence_count == 0:
                raise ValidationError(
                    "SUFFICIENT assessments require evidence_count > 0",
                )
            blocking = [
                gap_type.value
                for gap_type in self.gap_types
                if gap_type in BLOCKING_GAP_TYPES
            ]
            if blocking and self.assessment_current:
                raise ValidationError(
                    "SUFFICIENT assessments must not include blocking gap types: "
                    + ", ".join(blocking),
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "information_need_id": self.information_need_id,
            "research_question_id": self.research_question_id,
            "status": self.status.value,
            "evidence_count": self.evidence_count,
            "independent_source_count": self.independent_source_count,
            "source_quality": self.source_quality,
            "freshness": self.freshness,
            "source_diversity": self.source_diversity,
            "quantitative_evidence_present": self.quantitative_evidence_present,
            "contradictions": list(self.contradictions),
            "missing_aspects": list(self.missing_aspects),
            "gap_types": [gap_type.value for gap_type in self.gap_types],
            "search_directives": list(self.search_directives),
            "confidence": self.confidence,
            "reason": self.reason,
            "quality_contract_mode": self.quality_contract_mode,
            "required_aspect_ids": list(self.required_aspect_ids),
            "assessment_current": self.assessment_current,
            "assessment_evidence_fingerprint": self.assessment_evidence_fingerprint,
            "terminal_evidence_fingerprint": self.terminal_evidence_fingerprint,
            "terminal_evidence_count": self.terminal_evidence_count,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> InformationNeedAssessment:
        return cls(
            information_need_id=str(payload["information_need_id"]),
            research_question_id=str(payload["research_question_id"]),
            status=SufficiencyStatus(str(payload["status"])),
            evidence_count=int(payload.get("evidence_count", 0)),
            independent_source_count=int(payload.get("independent_source_count", 0)),
            source_quality=(
                float(payload["source_quality"])
                if payload.get("source_quality") is not None
                else None
            ),
            freshness=(
                float(payload["freshness"])
                if payload.get("freshness") is not None
                else None
            ),
            source_diversity=(
                float(payload["source_diversity"])
                if payload.get("source_diversity") is not None
                else None
            ),
            quantitative_evidence_present=payload.get("quantitative_evidence_present"),
            contradictions=tuple_of_str(payload.get("contradictions")),
            missing_aspects=tuple_of_str(payload.get("missing_aspects")),
            gap_types=tuple_of_enum(GapType, payload.get("gap_types")),
            search_directives=tuple_of_str(payload.get("search_directives")),
            confidence=(
                float(payload["confidence"])
                if payload.get("confidence") is not None
                else None
            ),
            reason=str(payload.get("reason", "")),
            quality_contract_mode=str(payload.get("quality_contract_mode", "")),
            required_aspect_ids=tuple_of_str(payload.get("required_aspect_ids")),
            assessment_current=bool(payload.get("assessment_current", True)),
            assessment_evidence_fingerprint=str(
                payload.get("assessment_evidence_fingerprint", "")
            ),
            terminal_evidence_fingerprint=str(
                payload.get("terminal_evidence_fingerprint", "")
            ),
            terminal_evidence_count=(
                int(payload["terminal_evidence_count"])
                if payload.get("terminal_evidence_count") is not None
                else None
            ),
        )

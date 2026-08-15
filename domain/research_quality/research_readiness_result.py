from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.common.exceptions import ValidationError
from domain.research_quality._helpers import tuple_of_str
from domain.research_quality.research_readiness_assessment import ResearchReadinessAssessment
from domain.research_quality.research_termination_reason import (
    BUDGET_CONTROLLED_TERMINATION_REASONS,
)
from domain.research_quality.sufficiency_status import ACTIONABLE_BLOCKING_STATUSES


def _has_actionable_blocking_gap(
    assessments: tuple[ResearchReadinessAssessment, ...],
) -> bool:
    return any(
        need.status in ACTIONABLE_BLOCKING_STATUSES or not need.assessment_current
        for assessment in assessments
        for need in assessment.information_need_assessments
    )


@dataclass(frozen=True)
class ResearchReadinessResult:
    """Run-level aggregate of research sufficiency across ResearchQuestions."""

    research_question_assessments: tuple[ResearchReadinessAssessment, ...]
    ready_for_analysis: bool
    blocking_research_question_ids: tuple[str, ...] = ()
    blocking_information_need_ids: tuple[str, ...] = ()
    targeted_research_required: bool = False
    termination_reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "research_question_assessments",
            tuple(self.research_question_assessments),
        )
        object.__setattr__(
            self,
            "blocking_research_question_ids",
            tuple_of_str(self.blocking_research_question_ids),
        )
        object.__setattr__(
            self,
            "blocking_information_need_ids",
            tuple_of_str(self.blocking_information_need_ids),
        )
        object.__setattr__(self, "termination_reason", str(self.termination_reason))

        rq_ids = {
            assessment.research_question_id
            for assessment in self.research_question_assessments
        }
        for rq_id in self.blocking_research_question_ids:
            if rq_id not in rq_ids:
                raise ValidationError(
                    f"blocking_research_question_ids contains unknown id: {rq_id!r}",
                )

        known_need_ids = {
            need.information_need_id
            for assessment in self.research_question_assessments
            for need in assessment.information_need_assessments
        }
        for need_id in self.blocking_information_need_ids:
            if need_id not in known_need_ids:
                raise ValidationError(
                    f"blocking_information_need_ids contains unknown id: {need_id!r}",
                )

        all_rq_ready = all(
            assessment.ready_for_analysis
            for assessment in self.research_question_assessments
        )
        if self.ready_for_analysis and not all_rq_ready:
            raise ValidationError(
                "ready_for_analysis=True requires all ResearchQuestion assessments "
                "to be ready",
            )
        if not self.ready_for_analysis and all_rq_ready:
            if self.research_question_assessments:
                raise ValidationError(
                    "ready_for_analysis=False is incompatible with all ResearchQuestion "
                    "assessments being ready",
                )

        if self.ready_for_analysis:
            if self.targeted_research_required:
                raise ValidationError(
                    "targeted_research_required must be False when ready_for_analysis=True",
                )
            if self.blocking_research_question_ids or self.blocking_information_need_ids:
                raise ValidationError(
                    "ready_for_analysis=True requires empty blocking id collections",
                )
        else:
            has_actionable_gap = _has_actionable_blocking_gap(
                self.research_question_assessments,
            )
            budget_controlled = (
                self.termination_reason in BUDGET_CONTROLLED_TERMINATION_REASONS
            )
            if has_actionable_gap and not self.targeted_research_required:
                if not budget_controlled:
                    raise ValidationError(
                        "targeted_research_required must be True when actionable "
                        "blocking gaps are present",
                    )
            if not has_actionable_gap and self.targeted_research_required:
                raise ValidationError(
                    "targeted_research_required must be False when all blocking "
                    "gaps are BLOCKED",
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "research_question_assessments": [
                assessment.to_dict()
                for assessment in self.research_question_assessments
            ],
            "ready_for_analysis": self.ready_for_analysis,
            "blocking_research_question_ids": list(
                self.blocking_research_question_ids,
            ),
            "blocking_information_need_ids": list(self.blocking_information_need_ids),
            "targeted_research_required": self.targeted_research_required,
            "termination_reason": self.termination_reason,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ResearchReadinessResult:
        return cls(
            research_question_assessments=tuple(
                ResearchReadinessAssessment.from_dict(item)
                for item in payload.get("research_question_assessments", [])
            ),
            ready_for_analysis=bool(payload["ready_for_analysis"]),
            blocking_research_question_ids=tuple_of_str(
                payload.get("blocking_research_question_ids"),
            ),
            blocking_information_need_ids=tuple_of_str(
                payload.get("blocking_information_need_ids"),
            ),
            targeted_research_required=bool(
                payload.get("targeted_research_required", False),
            ),
            termination_reason=str(payload.get("termination_reason", "")),
        )

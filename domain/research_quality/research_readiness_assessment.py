from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.common.exceptions import ValidationError
from domain.research_quality._helpers import tuple_of_str
from domain.research_quality.information_need_assessment import InformationNeedAssessment
from domain.research_quality.sufficiency_status import (
    READINESS_BLOCKING_STATUSES,
    SufficiencyStatus,
)


def _blocking_need_ids(
    assessments: tuple[InformationNeedAssessment, ...],
) -> tuple[str, ...]:
    return tuple(
        assessment.information_need_id
        for assessment in assessments
        if assessment.status in READINESS_BLOCKING_STATUSES
    )


@dataclass(frozen=True)
class ResearchReadinessAssessment:
    """Run-scoped readiness for one ResearchQuestion."""

    research_question_id: str
    information_need_assessments: tuple[InformationNeedAssessment, ...]
    ready_for_analysis: bool
    blocking_information_need_ids: tuple[str, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "research_question_id",
            str(self.research_question_id).strip(),
        )
        object.__setattr__(
            self,
            "information_need_assessments",
            tuple(self.information_need_assessments),
        )
        object.__setattr__(
            self,
            "blocking_information_need_ids",
            tuple_of_str(self.blocking_information_need_ids),
        )
        object.__setattr__(self, "reason", str(self.reason))

        if not self.research_question_id:
            raise ValidationError("research_question_id must not be empty")

        assessment_ids = {
            assessment.information_need_id
            for assessment in self.information_need_assessments
        }
        for assessment in self.information_need_assessments:
            if assessment.research_question_id != self.research_question_id:
                raise ValidationError(
                    "InformationNeedAssessment "
                    f"{assessment.information_need_id!r} belongs to "
                    f"{assessment.research_question_id!r}, expected "
                    f"{self.research_question_id!r}",
                )

        unknown_blocking = [
            need_id
            for need_id in self.blocking_information_need_ids
            if need_id not in assessment_ids
        ]
        if unknown_blocking:
            raise ValidationError(
                "blocking_information_need_ids reference unknown assessments: "
                + ", ".join(unknown_blocking),
            )

        expected_blocking = _blocking_need_ids(self.information_need_assessments)
        if self.ready_for_analysis:
            blocking_statuses = [
                assessment.status.value
                for assessment in self.information_need_assessments
                if assessment.status in READINESS_BLOCKING_STATUSES
            ]
            if blocking_statuses:
                raise ValidationError(
                    "ready_for_analysis=True is incompatible with blocking statuses: "
                    + ", ".join(blocking_statuses),
                )
            if self.blocking_information_need_ids:
                raise ValidationError(
                    "ready_for_analysis=True requires empty "
                    "blocking_information_need_ids",
                )
        else:
            if not expected_blocking:
                raise ValidationError(
                    "ready_for_analysis=False requires at least one blocking "
                    "InformationNeed assessment",
                )
            if set(self.blocking_information_need_ids) != set(expected_blocking):
                raise ValidationError(
                    "blocking_information_need_ids must match assessments with "
                    "blocking statuses",
                )

        if any(
            assessment.status != SufficiencyStatus.SUFFICIENT
            for assessment in self.information_need_assessments
        ) and self.ready_for_analysis:
            raise ValidationError(
                "ready_for_analysis=True requires all InformationNeed assessments "
                "to be SUFFICIENT",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "research_question_id": self.research_question_id,
            "information_need_assessments": [
                assessment.to_dict()
                for assessment in self.information_need_assessments
            ],
            "ready_for_analysis": self.ready_for_analysis,
            "blocking_information_need_ids": list(self.blocking_information_need_ids),
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ResearchReadinessAssessment:
        return cls(
            research_question_id=str(payload["research_question_id"]),
            information_need_assessments=tuple(
                InformationNeedAssessment.from_dict(item)
                for item in payload.get("information_need_assessments", [])
            ),
            ready_for_analysis=bool(payload["ready_for_analysis"]),
            blocking_information_need_ids=tuple_of_str(
                payload.get("blocking_information_need_ids"),
            ),
            reason=str(payload.get("reason", "")),
        )

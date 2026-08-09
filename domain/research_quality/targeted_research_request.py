from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.common.exceptions import ValidationError
from domain.research_quality._helpers import tuple_of_enum, tuple_of_str
from domain.research_quality.gap_type import GapType

MAX_TARGETED_SEARCH_DIRECTIVES = 5


@dataclass(frozen=True)
class TargetedResearchRequest:
    """Bounded targeted research contract scoped to one existing InformationNeed."""

    workflow_run_id: str
    research_design_id: str
    research_question_id: str
    information_need_id: str
    gap_types: tuple[GapType, ...]
    missing_aspects: tuple[str, ...] = ()
    search_directives: tuple[str, ...] = ()
    attempt: int = 1
    existing_source_ids: tuple[str, ...] = ()
    existing_evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "workflow_run_id", str(self.workflow_run_id).strip())
        object.__setattr__(
            self,
            "research_design_id",
            str(self.research_design_id).strip(),
        )
        object.__setattr__(
            self,
            "research_question_id",
            str(self.research_question_id).strip(),
        )
        object.__setattr__(
            self,
            "information_need_id",
            str(self.information_need_id).strip(),
        )
        object.__setattr__(
            self,
            "gap_types",
            tuple_of_enum(GapType, self.gap_types),
        )
        object.__setattr__(self, "missing_aspects", tuple_of_str(self.missing_aspects))
        object.__setattr__(
            self,
            "search_directives",
            tuple_of_str(self.search_directives),
        )
        object.__setattr__(
            self,
            "existing_source_ids",
            tuple_of_str(self.existing_source_ids),
        )
        object.__setattr__(
            self,
            "existing_evidence_ids",
            tuple_of_str(self.existing_evidence_ids),
        )

        if not self.workflow_run_id:
            raise ValidationError("workflow_run_id must not be empty")
        if not self.research_design_id:
            raise ValidationError("research_design_id must not be empty")
        if not self.research_question_id:
            raise ValidationError("research_question_id must not be empty")
        if not self.information_need_id:
            raise ValidationError("information_need_id must not be empty")
        if self.attempt < 1:
            raise ValidationError("attempt must be >= 1")
        if len(self.search_directives) > MAX_TARGETED_SEARCH_DIRECTIVES:
            raise ValidationError("search_directives must contain at most 5 items")

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_run_id": self.workflow_run_id,
            "research_design_id": self.research_design_id,
            "research_question_id": self.research_question_id,
            "information_need_id": self.information_need_id,
            "gap_types": [gap_type.value for gap_type in self.gap_types],
            "missing_aspects": list(self.missing_aspects),
            "search_directives": list(self.search_directives),
            "attempt": self.attempt,
            "existing_source_ids": list(self.existing_source_ids),
            "existing_evidence_ids": list(self.existing_evidence_ids),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TargetedResearchRequest:
        return cls(
            workflow_run_id=str(payload["workflow_run_id"]),
            research_design_id=str(payload["research_design_id"]),
            research_question_id=str(payload["research_question_id"]),
            information_need_id=str(payload["information_need_id"]),
            gap_types=tuple_of_enum(GapType, payload.get("gap_types")),
            missing_aspects=tuple_of_str(payload.get("missing_aspects")),
            search_directives=tuple_of_str(payload.get("search_directives")),
            attempt=int(payload.get("attempt", 1)),
            existing_source_ids=tuple_of_str(payload.get("existing_source_ids")),
            existing_evidence_ids=tuple_of_str(payload.get("existing_evidence_ids")),
        )

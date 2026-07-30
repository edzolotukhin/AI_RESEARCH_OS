"""
AI Research OS

Planner Plan DTO.

Immutable transport object representing a complete research plan
produced by the Planner parser.

DTOs contain no business logic and serve as the boundary between
external planner responses and the domain model.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from .research_stage_dto import ResearchStageDTO


def _empty_metadata() -> Mapping[str, Any]:
    """Return an immutable empty metadata mapping."""
    return MappingProxyType({})


@dataclass(frozen=True, slots=True)
class PlannerPlanDTO:
    """
    Immutable transport object for a research plan.
    """

    name: str
    goal: str
    methodology: str = ""
    stages: tuple[ResearchStageDTO, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        """
        Ensure metadata is always immutable.
        """

        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(
                self,
                "metadata",
                MappingProxyType(dict(self.metadata)),
            )
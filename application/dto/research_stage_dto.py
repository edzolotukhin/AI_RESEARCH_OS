"""
AI Research OS

Research Stage DTO.

Immutable transport object representing a logical research stage
produced by the Planner parser.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .planner_task_dto import PlannerTaskDTO


@dataclass(frozen=True, slots=True)
class ResearchStageDTO:
    """
    Immutable transport object for a research stage.
    """

    id: str
    name: str
    description: str = ""
    tasks: tuple[PlannerTaskDTO, ...] = field(default_factory=tuple)
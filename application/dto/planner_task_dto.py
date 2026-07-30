"""
AI Research OS

Planner Task DTO.

Transport object representing a planning task produced by the
Planner parser.

DTOs contain no business logic and are immutable.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PlannerTaskDTO:
    """
    Immutable transport object for a planner task.
    """

    id: str
    title: str
    description: str = ""
    executor_id: str = ""
    dependencies: tuple[str, ...] = field(default_factory=tuple)

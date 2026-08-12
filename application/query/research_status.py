"""Projected Research execution status and phase (P1-19.1).

Read-only projections over durable WorkflowRun/task state. Not persisted.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from application.query.research_run_result import ResearchRunOutcome


class ResearchExecutionStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    TERMINAL = "TERMINAL"


class ResearchPhase(str, Enum):
    QUEUED = "QUEUED"
    PLANNING = "PLANNING"
    RESEARCHING = "RESEARCHING"
    EVALUATING = "EVALUATING"
    ANALYZING = "ANALYZING"
    WRITING = "WRITING"
    REVIEWING = "REVIEWING"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True)
class ResearchStatusProjection:
    research_id: str
    project_id: str
    execution_status: ResearchExecutionStatus
    phase: ResearchPhase
    product_outcome: ResearchRunOutcome | None
    result_available: bool
    workflow_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "research_id": self.research_id,
            "run_id": self.research_id,
            "project_id": self.project_id,
            "execution_status": self.execution_status.value,
            "phase": self.phase.value,
            "product_outcome": (
                self.product_outcome.value if self.product_outcome is not None else None
            ),
            "result_available": self.result_available,
            "workflow_status": self.workflow_status,
            "status_url": f"/research/{self.research_id}",
            "result_url": f"/research/{self.research_id}/result",
        }

from __future__ import annotations

from enum import Enum

from application.qualitative.service import QUAL_TEMPLATE
from application.quantitative.workflow import (
    CMF_QUANTITATIVE_WORKFLOW_ID,
    QUANTITATIVE_WORKFLOW_ID,
)


class WorkflowKind(str, Enum):
    PROJECT_DESIGN = "project_design"
    DESK = "desk"
    QUANTITATIVE = "quantitative"
    QUALITATIVE = "qualitative"
    UNKNOWN = "unknown"


_DESK_EXECUTOR_SEQUENCES = {
    ("search", "evidence", "research_quality", "analysis", "report", "review"),
    ("search", "evidence", "research_quality", "analysis", "report", "review", "finalization"),
    ("report", "review", "finalization"),
    ("search", "evidence", "research_quality", "analysis", "report", "review", "revision", "review", "finalization"),
    ("report", "review", "revision", "review", "finalization"),
}


def classify_workflow_template(template) -> WorkflowKind:
    """Classify an immutable workflow-template snapshot without negative inference."""
    template_id = str(getattr(template, "id", ""))
    kind = classify_workflow_template_id(template_id)
    if kind != WorkflowKind.UNKNOWN:
        return kind
    executors = tuple(
        str(getattr(definition, "executor_id", ""))
        for definition in getattr(template, "task_definitions", ())
    )
    if (
        executors in _DESK_EXECUTOR_SEQUENCES
        and getattr(template, "research_design_snapshot", None) is not None
    ):
        return WorkflowKind.DESK
    return WorkflowKind.UNKNOWN


def classify_workflow_template_id(template_id: str) -> WorkflowKind:
    """Classify template identities that have a stable canonical namespace."""
    if template_id.startswith("project-design:"):
        return WorkflowKind.PROJECT_DESIGN
    if template_id in {QUANTITATIVE_WORKFLOW_ID, CMF_QUANTITATIVE_WORKFLOW_ID}:
        return WorkflowKind.QUANTITATIVE
    if template_id == QUAL_TEMPLATE:
        return WorkflowKind.QUALITATIVE
    return WorkflowKind.UNKNOWN

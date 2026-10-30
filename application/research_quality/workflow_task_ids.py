from __future__ import annotations

TASK_ASSESS_RESEARCH_READINESS = "task-assess-research-readiness"
EXECUTOR_RESEARCH_QUALITY = "research_quality"

DOWNSTREAM_TASK_DEFINITION_IDS = frozenset(
    {
        "task-analyze",
        "task-write-report",
        "task-review-report",
        "task-review-report-1",
        "task-revise-report",
        "task-review-report-2",
        "task-finalize-deliverables",
    },
)

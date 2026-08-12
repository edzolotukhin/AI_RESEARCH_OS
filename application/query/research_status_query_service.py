"""Deterministic Research status/phase projection over durable run state."""

from __future__ import annotations

from application.persistence.exceptions import EntityNotFoundError
from application.ports.workflow_run_repository import WorkflowRunRepository
from application.query.research_run_result import (
    ResearchRunOutcome,
    ResearchRunResultProjectionError,
)
from application.query.research_run_result_query_service import (
    ResearchRunResultQueryService,
)
from application.query.research_status import (
    ResearchExecutionStatus,
    ResearchPhase,
    ResearchStatusProjection,
)
from domain.value_objects.task_status import TaskStatus
from domain.workflow_run import WorkflowRun
from domain.workflow_status import WorkflowStatus

_PHASE_RANK: dict[ResearchPhase, int] = {
    ResearchPhase.QUEUED: 0,
    ResearchPhase.PLANNING: 1,
    ResearchPhase.RESEARCHING: 2,
    ResearchPhase.EVALUATING: 3,
    ResearchPhase.ANALYZING: 4,
    ResearchPhase.WRITING: 5,
    ResearchPhase.REVIEWING: 6,
    ResearchPhase.COMPLETED: 7,
}

_DEFINITION_PHASE: dict[str, ResearchPhase] = {
    "task-plan": ResearchPhase.PLANNING,
    "task-planner": ResearchPhase.PLANNING,
    "planner": ResearchPhase.PLANNING,
    "task-collect-evidence": ResearchPhase.RESEARCHING,
    "task-extract-evidence": ResearchPhase.RESEARCHING,
    "task-assess-research-readiness": ResearchPhase.EVALUATING,
    "task-analyze": ResearchPhase.ANALYZING,
    "task-write-report": ResearchPhase.WRITING,
    "task-review-report": ResearchPhase.REVIEWING,
}

_PIPELINE_ORDER: tuple[tuple[str, ResearchPhase], ...] = (
    ("task-collect-evidence", ResearchPhase.RESEARCHING),
    ("task-extract-evidence", ResearchPhase.RESEARCHING),
    ("task-assess-research-readiness", ResearchPhase.EVALUATING),
    ("task-analyze", ResearchPhase.ANALYZING),
    ("task-write-report", ResearchPhase.WRITING),
    ("task-review-report", ResearchPhase.REVIEWING),
)

_ACTIVE_TASK_STATUSES = frozenset(
    {
        TaskStatus.RUNNING,
        TaskStatus.READY,
        TaskStatus.WAITING,
    },
)
_RUNNING_TASK_STATUSES = frozenset({TaskStatus.RUNNING})
_READY_TASK_STATUSES = frozenset({TaskStatus.READY})


class ResearchStatusQueryService:
    """Pure read projection of Research execution_status and phase."""

    def __init__(
        self,
        *,
        workflow_run_repository: WorkflowRunRepository,
        research_run_result_query_service: ResearchRunResultQueryService | None = None,
    ) -> None:
        self._workflow_run_repository = workflow_run_repository
        self._result_query = research_run_result_query_service

    def get_status(self, research_id: str) -> ResearchStatusProjection:
        workflow_run = self._workflow_run_repository.get_by_id(research_id)
        if workflow_run is None:
            raise EntityNotFoundError(f"Research not found: {research_id}")

        execution_status = self.project_execution_status(workflow_run)
        phase = self.project_phase(workflow_run)
        product_outcome: ResearchRunOutcome | None = None
        result_available = False
        if execution_status == ResearchExecutionStatus.TERMINAL:
            if self._result_query is not None:
                try:
                    product_outcome = self._result_query.get_for_run(
                        research_id,
                    ).outcome
                    result_available = True
                except ResearchRunResultProjectionError:
                    product_outcome = None
                    result_available = False
            else:
                result_available = True

        return ResearchStatusProjection(
            research_id=workflow_run.id,
            project_id=workflow_run.project_id,
            execution_status=execution_status,
            phase=phase,
            product_outcome=product_outcome,
            result_available=result_available,
            workflow_status=workflow_run.status.value,
        )

    @staticmethod
    def project_execution_status(workflow_run: WorkflowRun) -> ResearchExecutionStatus:
        if workflow_run.is_terminal:
            return ResearchExecutionStatus.TERMINAL
        if workflow_run.status in {
            WorkflowStatus.RUNNING,
            WorkflowStatus.PAUSED,
        }:
            return ResearchExecutionStatus.RUNNING
        return ResearchExecutionStatus.QUEUED

    @classmethod
    def project_phase(cls, workflow_run: WorkflowRun) -> ResearchPhase:
        if workflow_run.is_terminal:
            return ResearchPhase.COMPLETED

        running_phases = [
            cls._phase_for_task(task)
            for task in workflow_run.tasks
            if task.status in _RUNNING_TASK_STATUSES
        ]
        running_phases = [phase for phase in running_phases if phase is not None]
        if running_phases:
            return max(running_phases, key=lambda item: _PHASE_RANK[item])

        ready_phases = [
            cls._phase_for_task(task)
            for task in workflow_run.tasks
            if task.status in _READY_TASK_STATUSES
        ]
        ready_phases = [phase for phase in ready_phases if phase is not None]
        if ready_phases:
            return min(ready_phases, key=lambda item: _PHASE_RANK[item])

        # Infer from pipeline progress: first incomplete stage after completed work.
        by_definition = {task.definition_id: task for task in workflow_run.tasks}
        furthest_completed = ResearchPhase.QUEUED
        any_started = any(
            task.status != TaskStatus.CREATED for task in workflow_run.tasks
        )
        if (
            not any_started
            and workflow_run.status
            in {WorkflowStatus.CREATED, WorkflowStatus.READY}
        ):
            return ResearchPhase.QUEUED

        for definition_id, phase in _PIPELINE_ORDER:
            task = by_definition.get(definition_id)
            if task is None:
                continue
            if task.status == TaskStatus.COMPLETED:
                furthest_completed = phase
                continue
            if task.status == TaskStatus.SKIPPED:
                continue
            if task.status == TaskStatus.CREATED:
                if furthest_completed == ResearchPhase.QUEUED and not any_started:
                    return ResearchPhase.QUEUED
                return phase
            if task.status in {TaskStatus.FAILED, TaskStatus.CANCELLED}:
                return phase
            return phase

        if furthest_completed != ResearchPhase.QUEUED:
            return furthest_completed

        for task in workflow_run.tasks:
            if task.executor_id == "planner" or "plan" in task.definition_id:
                if task.status in _ACTIVE_TASK_STATUSES:
                    return ResearchPhase.PLANNING

        if workflow_run.status in {WorkflowStatus.CREATED, WorkflowStatus.READY}:
            return ResearchPhase.QUEUED
        if workflow_run.status == WorkflowStatus.RUNNING:
            return ResearchPhase.RESEARCHING
        return ResearchPhase.QUEUED

    @staticmethod
    def _phase_for_task(task) -> ResearchPhase | None:
        if task.definition_id in _DEFINITION_PHASE:
            return _DEFINITION_PHASE[task.definition_id]
        if task.executor_id == "planner":
            return ResearchPhase.PLANNING
        if task.executor_id in {"search", "evidence"}:
            return ResearchPhase.RESEARCHING
        if task.executor_id == "research_quality":
            return ResearchPhase.EVALUATING
        if task.executor_id == "analysis":
            return ResearchPhase.ANALYZING
        if task.executor_id == "report":
            return ResearchPhase.WRITING
        if task.executor_id == "review":
            return ResearchPhase.REVIEWING
        return None

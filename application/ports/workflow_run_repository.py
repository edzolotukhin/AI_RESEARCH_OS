from __future__ import annotations

from typing import Any, Protocol

from domain.workflow_run import WorkflowRun
from domain.workflow_status import WorkflowStatus


class WorkflowRunRepository(Protocol):
    """
    Persistence port for the WorkflowRun runtime aggregate.

    Task, TaskDependencyGraph, and task result summaries are persisted only
    through this aggregate root. There is no TaskRepository.

    Repositories persist aggregates; they never construct or assemble domain
    state. WorkflowRun assembly belongs to WorkflowRunFactory (application layer).
    """

    def create(
        self,
        workflow_run: WorkflowRun,
        *,
        project_id: str,
    ) -> None:
        """
        Persist a new, fully constructed WorkflowRun aggregate.

        The aggregate must already exist (built by WorkflowRunFactory).
        Initializes persistence version to 0.
        Raises DuplicateEntityError when workflow_run.id already exists.
        """
        ...

    def get_by_id(self, run_id: str) -> WorkflowRun | None:
        """Load a workflow run aggregate by identifier."""
        ...

    def save(
        self,
        workflow_run: WorkflowRun,
        *,
        expected_version: int | None = None,
        task_results: dict[str, Any] | None = None,
    ) -> int:
        """
        Persist modifications to an existing workflow run aggregate.

        Raises EntityNotFoundError when the aggregate was never created.
        Optional task_results maps task_id to a durable result summary.
        Returns the new aggregate version.
        """
        ...

    def get_task_results(self, run_id: str) -> dict[str, Any]:
        """Return durable task result summaries stored for a run."""
        ...

    def get_version(self, run_id: str) -> int:
        """Return the current optimistic-lock version for a persisted run."""
        ...

    def list_for_project(
        self,
        project_id: str,
        *,
        status: WorkflowStatus | None = None,
    ) -> list[WorkflowRun]:
        """List workflow runs for a project, optionally filtered by status."""
        ...

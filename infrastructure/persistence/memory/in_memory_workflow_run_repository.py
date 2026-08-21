from __future__ import annotations

import copy
from typing import Any

from application.persistence.exceptions import (
    ConcurrentModificationError,
    DuplicateEntityError,
    EntityNotFoundError,
)
from application.ports.workflow_run_repository import WorkflowRunRepository
from domain.workflow_run import WorkflowRun
from domain.workflow_status import WorkflowStatus


class InMemoryWorkflowRunRepository:
    """In-memory WorkflowRunRepository adapter."""

    def __init__(self) -> None:
        self._runs: dict[str, WorkflowRun] = {}
        self._versions: dict[str, int] = {}
        self._project_index: dict[str, list[str]] = {}
        self._task_results: dict[str, dict[str, Any]] = {}

    def create(
        self,
        workflow_run: WorkflowRun,
        *,
        project_id: str,
    ) -> None:
        if workflow_run.id in self._runs:
            raise DuplicateEntityError(
                f"WorkflowRun already exists: {workflow_run.id}"
            )

        stored = copy.deepcopy(workflow_run)
        stored.project_id = project_id
        self._runs[workflow_run.id] = stored
        self._versions[workflow_run.id] = 0
        self._task_results[workflow_run.id] = {}

        project_runs = self._project_index.setdefault(project_id, [])
        project_runs.append(workflow_run.id)

    def get_by_id(self, run_id: str) -> WorkflowRun | None:
        workflow_run = self._runs.get(run_id)
        if workflow_run is None:
            return None
        return copy.deepcopy(workflow_run)

    def delete(self, run_id: str) -> None:
        workflow_run = self._runs.pop(run_id, None)
        if workflow_run is None:
            raise EntityNotFoundError(f"WorkflowRun not found: {run_id}")
        self._versions.pop(run_id, None)
        self._task_results.pop(run_id, None)
        project_runs = self._project_index.get(workflow_run.project_id, [])
        if run_id in project_runs:
            project_runs.remove(run_id)

    def save(
        self,
        workflow_run: WorkflowRun,
        *,
        expected_version: int | None = None,
        task_results: dict[str, Any] | None = None,
    ) -> int:
        current_version = self._versions.get(workflow_run.id)
        if current_version is None:
            raise EntityNotFoundError(
                f"WorkflowRun not found: {workflow_run.id}"
            )

        if (
            expected_version is not None
            and expected_version != current_version
        ):
            raise ConcurrentModificationError(
                f"WorkflowRun {workflow_run.id} version mismatch: "
                f"expected {expected_version}, found {current_version}."
            )

        self._runs[workflow_run.id] = copy.deepcopy(workflow_run)
        if task_results is not None:
            self._task_results[workflow_run.id] = copy.deepcopy(task_results)

        new_version = current_version + 1
        self._versions[workflow_run.id] = new_version
        return new_version

    def get_task_results(self, run_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._task_results.get(run_id, {}))

    def get_version(self, run_id: str) -> int:
        if run_id not in self._runs:
            raise EntityNotFoundError(f"WorkflowRun not found: {run_id}")
        return self._versions[run_id]

    def list_for_project(
        self,
        project_id: str,
        *,
        status: WorkflowStatus | None = None,
    ) -> list[WorkflowRun]:
        run_ids = self._project_index.get(project_id, [])
        runs = [
            copy.deepcopy(self._runs[run_id])
            for run_id in run_ids
            if run_id in self._runs
        ]

        if status is None:
            return runs

        return [run for run in runs if run.status == status]

from __future__ import annotations

from typing import Any

from application.persistence.exceptions import EntityNotFoundError
from application.ports.workflow_run_repository import WorkflowRunRepository
from application.ports.workflow_template_repository import (
    WorkflowTemplateRepository,
)
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.workflow_run import WorkflowRun
from domain.workflow_status import WorkflowStatus
from domain.workflow_template import WorkflowTemplate


class WorkflowService:
    """
    Coordinates workflow definition and runtime persistence use cases.

    WorkflowRunFactory constructs WorkflowRun aggregates; repositories persist
    them. This service does not perform domain state transitions.
    """

    def __init__(
        self,
        *,
        workflow_template_repository: WorkflowTemplateRepository,
        workflow_run_repository: WorkflowRunRepository,
        workflow_run_factory: WorkflowRunFactory,
    ) -> None:
        self._workflow_template_repository = workflow_template_repository
        self._workflow_run_repository = workflow_run_repository
        self._workflow_run_factory = workflow_run_factory

    def publish_template_snapshot(
        self,
        template: WorkflowTemplate,
        *,
        project_id: str,
    ) -> None:
        self._workflow_template_repository.save_snapshot(
            template,
            project_id=project_id,
        )

    def get_template(self, template_id: str) -> WorkflowTemplate:
        template = self._workflow_template_repository.get_by_id(template_id)
        if template is None:
            raise EntityNotFoundError(
                f"WorkflowTemplate not found: {template_id}"
            )
        return template

    def list_templates_for_project(
        self,
        project_id: str,
    ) -> list[WorkflowTemplate]:
        return self._workflow_template_repository.list_for_project(project_id)

    def create_workflow_run(
        self,
        template: WorkflowTemplate,
        *,
        project_id: str,
        run_id: str | None = None,
    ) -> WorkflowRun:
        workflow_run = self._workflow_run_factory.create(
            template=template,
            run_id=run_id,
        )
        self._workflow_run_repository.create(
            workflow_run,
            project_id=project_id,
        )
        return workflow_run

    def get_workflow_run(self, run_id: str) -> WorkflowRun:
        workflow_run = self._workflow_run_repository.get_by_id(run_id)
        if workflow_run is None:
            raise EntityNotFoundError(f"WorkflowRun not found: {run_id}")
        return workflow_run

    def list_workflow_runs_for_project(
        self,
        project_id: str,
        *,
        status: WorkflowStatus | None = None,
    ) -> list[WorkflowRun]:
        return self._workflow_run_repository.list_for_project(
            project_id,
            status=status,
        )

    def save_workflow_run(
        self,
        workflow_run: WorkflowRun,
        *,
        expected_version: int | None = None,
        task_results: dict[str, Any] | None = None,
    ) -> int:
        return self._workflow_run_repository.save(
            workflow_run,
            expected_version=expected_version,
            task_results=task_results,
        )

    def get_task_results(self, run_id: str) -> dict[str, Any]:
        return self._workflow_run_repository.get_task_results(run_id)

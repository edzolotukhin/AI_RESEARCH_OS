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
        initially_paused: bool = False,
    ) -> WorkflowRun:
        workflow_run = self._workflow_run_factory.create(
            template=template,
            run_id=run_id,
            project_id=project_id,
        )
        if initially_paused:
            # Persist the setup-gated state atomically.  A CREATED run is
            # worker-claimable, so transitioning after create would leave a
            # race in which an incomplete user-operated workflow could run.
            workflow_run.ready()
            workflow_run.start()
            workflow_run.pause()
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

    def delete_workflow_run(self, run_id: str) -> None:
        """Compensate a failed aggregate-creation boundary."""
        self._workflow_run_repository.delete(run_id)

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
        quant_pin_binding: dict[str, Any] | None = None,
    ) -> int:
        if quant_pin_binding is not None:
            from application.methods.quantitative.pin import (
                METHOD_PIN, ANALYSIS_PIN, resolve_method_pin, verify_analysis_state,
            )
            if workflow_run.workflow_template_id != "quantitative-consumer-survey-cmf-v1":
                raise ValueError("Quant pin binding requires a CMF Quant run")
            if METHOD_PIN in quant_pin_binding:
                resolve_method_pin(quant_pin_binding[METHOD_PIN], project_id=workflow_run.project_id,
                                   run_id=workflow_run.id)
            if ANALYSIS_PIN in quant_pin_binding:
                existing = self._workflow_run_repository.get_task_results(workflow_run.id)
                if METHOD_PIN not in existing:
                    raise ValueError("Quant analysis requires a persisted method pin")
                if task_results is None or not isinstance(task_results.get("quantitative"), dict):
                    raise ValueError("Quant analysis requires persisted safe state")
                analysis_pin = quant_pin_binding[ANALYSIS_PIN]
                if (analysis_pin.get("project_id"), analysis_pin.get("run_id")) != (
                    workflow_run.project_id, workflow_run.id
                ) or analysis_pin.get("contract") != "CMF_QUANT_ANALYSIS_V1":
                    raise ValueError("Quant analysis pin scope is invalid")
                verify_analysis_state(analysis_pin, method_pin=existing[METHOD_PIN],
                                      state=task_results["quantitative"])
        save_kwargs: dict[str, Any] = {
            "expected_version": expected_version,
            "task_results": task_results,
        }
        if quant_pin_binding is not None:
            save_kwargs["quant_pin_binding"] = quant_pin_binding
        return self._workflow_run_repository.save(workflow_run, **save_kwargs)

    def get_task_results(self, run_id: str) -> dict[str, Any]:
        return self._workflow_run_repository.get_task_results(run_id)

    def get_workflow_run_version(self, run_id: str) -> int:
        return self._workflow_run_repository.get_version(run_id)

from __future__ import annotations

from application.persistence.exceptions import EntityNotFoundError
from application.ports.execution_log_store import ExecutionLogStore
from application.runtime.interrupted_task_recovery import (
    INTERRUPTED_RUNNING_TASK_REASON,
    recover_interrupted_running_tasks,
)
from application.runtime.task_result_codec import restore_runtime_state
from application.runtime.workflow_execution_audit import WorkflowExecutionAudit
from application.runtime.workflow_runtime_persister import WorkflowRuntimePersister
from application.services.project_service import ProjectService
from application.services.workflow_service import WorkflowService
from application.workflow_engine import WorkflowEngine
from domain.project import Project
from domain.workflow_status import WorkflowStatus
from domain.workflow_template import WorkflowTemplate
from runtime.workflow_context import WorkflowContext


class DurableWorkflowService:
    """
    Coordinates durable workflow execution without owning domain transitions.

    Persists template snapshots, WorkflowRun checkpoints, task results, and
    append-only execution audit events while delegating orchestration to
    WorkflowEngine.
    """

    def __init__(
        self,
        *,
        workflow_service: WorkflowService,
        project_service: ProjectService,
        execution_log_store: ExecutionLogStore,
        workflow_engine: WorkflowEngine,
    ) -> None:
        self._workflow_service = workflow_service
        self._project_service = project_service
        self._audit = WorkflowExecutionAudit(execution_log_store)
        self._workflow_engine = workflow_engine

    def start_research(
        self,
        project: Project,
        workflow_template: WorkflowTemplate,
        *,
        run_id: str | None = None,
    ) -> WorkflowContext:
        self._workflow_service.publish_template_snapshot(
            workflow_template,
            project_id=project.id,
        )
        workflow_run = self._workflow_service.create_workflow_run(
            workflow_template,
            project_id=project.id,
            run_id=run_id,
        )

        context = WorkflowContext(
            project=project,
            workflow_template=workflow_template,
            workflow_run=workflow_run,
        )
        self._audit.workflow_created(workflow_run.id)

        persister = WorkflowRuntimePersister(
            workflow_service=self._workflow_service,
            audit=self._audit,
            run_id=workflow_run.id,
            initial_version=0,
        )
        return self._execute(context, persister)

    def resume_research(self, run_id: str) -> WorkflowContext:
        workflow_run = self._workflow_service.get_workflow_run(run_id)
        project = self._project_service.get_project(workflow_run.project_id)
        workflow_template = self._workflow_service.get_template(
            workflow_run.workflow_template_id,
        )
        task_results = self._workflow_service.get_task_results(run_id)

        context = WorkflowContext(
            project=project,
            workflow_template=workflow_template,
            workflow_run=workflow_run,
        )
        restore_runtime_state(context, task_results)

        if workflow_run.is_terminal:
            return context

        if workflow_run.status == WorkflowStatus.PAUSED:
            raise RuntimeError(
                "PAUSED WorkflowRun resume is outside PF-04 durable execution scope."
            )

        recovered_tasks = recover_interrupted_running_tasks(workflow_run)
        resume_version = self._workflow_service.get_workflow_run_version(run_id)
        self._audit.workflow_resumed(run_id, resume_version=resume_version)

        persister = WorkflowRuntimePersister(
            workflow_service=self._workflow_service,
            audit=self._audit,
            run_id=run_id,
            initial_version=resume_version,
            task_results=task_results,
        )

        for task in recovered_tasks:
            context.current_task = task
            persister.on_task_finished(
                context,
                error=RuntimeError(INTERRUPTED_RUNNING_TASK_REASON),
            )

        return self._execute(context, persister)

    def _execute(
        self,
        context: WorkflowContext,
        persister: WorkflowRuntimePersister,
    ) -> WorkflowContext:
        return self._workflow_engine.run(
            context,
            checkpoint=persister,
        )

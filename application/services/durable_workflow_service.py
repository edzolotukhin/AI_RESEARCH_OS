from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Mapping, Protocol

from application.execution.exceptions import ClaimConflictError
from application.execution.lease_config import LeaseConfig
from application.ports.run_queue import RunQueue
from application.ports.workflow_run_execution_port import WorkflowRunExecutionPort
from application.persistence.exceptions import EntityNotFoundError
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
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus
from domain.workflow_template import WorkflowTemplate
from runtime.workflow_context import WorkflowContext

from application.execution.heartbeat import LeaseGuard


class WorkflowContextServiceResolver(Protocol):
    def resolve(self, context: WorkflowContext) -> Mapping[str, object]: ...


class DurableWorkflowService:
    """
    Coordinates durable workflow execution without owning domain transitions.

    PF-06 splits submission (HTTP) from execution (worker).
    """

    def __init__(
        self,
        *,
        workflow_service: WorkflowService,
        project_service: ProjectService,
        execution_log_store: object,
        workflow_engine: WorkflowEngine,
        execution_port: WorkflowRunExecutionPort | None = None,
        run_queue: RunQueue | None = None,
        lease_config: LeaseConfig | None = None,
        context_service_resolver: WorkflowContextServiceResolver | None = None,
    ) -> None:
        self._workflow_service = workflow_service
        self._project_service = project_service
        self._audit = WorkflowExecutionAudit(execution_log_store)
        self._workflow_engine = workflow_engine
        self._execution_port = execution_port
        self._run_queue = run_queue
        self._lease_config = lease_config or LeaseConfig()
        self._context_service_resolver = context_service_resolver

    def activate_paused_run(
        self,
        run_id: str,
        *,
        shared_state: dict[str, object],
        completed_task_definition_ids: tuple[str, ...] = (),
        skipped_task_definition_ids: tuple[str, ...] = (),
    ) -> WorkflowContext:
        """Persist one authorized PAUSED -> RUNNING transition for worker claim."""
        workflow_run = self._workflow_service.get_workflow_run(run_id)
        if workflow_run.is_terminal:
            return self._load_context(run_id)
        if workflow_run.status is not WorkflowStatus.PAUSED:
            raise RuntimeError("WorkflowRun is not awaiting authorized activation.")
        version = self._workflow_service.get_workflow_run_version(run_id)
        completed = set(completed_task_definition_ids)
        skipped = set(skipped_task_definition_ids)
        if completed.intersection(skipped):
            raise RuntimeError("Task cannot be both completed and skipped at activation.")
        activation_results: dict[str, object] = {}
        for task in workflow_run.tasks:
            if task.definition_id in completed and not task.is_terminal:
                task.ready()
                task.start()
                task.complete()
                activation_results[task.id] = {
                    "task_id": task.id,
                    "definition_id": task.definition_id,
                    "shared_state": shared_state,
                }
            elif task.definition_id in skipped and not task.is_terminal:
                workflow_run.skip_task_as_satisfied_dependency(task)
                activation_results[task.id] = {
                    "task_id": task.id,
                    "definition_id": task.definition_id,
                    "shared_state": shared_state,
                    "status": "skipped_explicit_unweighted",
                }
        workflow_run.resume()
        self._workflow_service.save_workflow_run(
            workflow_run,
            expected_version=version,
            task_results=activation_results,
        )
        self._notify_runnable(run_id)
        return self._load_context(run_id)

    def submit_research(
        self,
        project: Project,
        workflow_template: WorkflowTemplate,
        *,
        run_id: str | None = None,
    ) -> WorkflowContext:
        """Persist a runnable workflow run without executing it."""
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
        self._notify_runnable(workflow_run.id)
        return context

    def submit_resume(self, run_id: str) -> WorkflowContext:
        """Validate and mark a run runnable without executing it inline."""
        context = self._load_context(run_id)
        workflow_run = context.workflow_run

        if workflow_run.is_terminal:
            return context

        if workflow_run.status == WorkflowStatus.PAUSED:
            raise RuntimeError(
                "PAUSED WorkflowRun resume is outside PF-04 durable execution scope."
            )

        if self._execution_port is not None:
            lease = self._execution_port.get_lease(run_id)
            if lease is not None:
                now = datetime.now(timezone.utc)
                if lease.lease_expires_at >= now:
                    raise ClaimConflictError(
                        f"WorkflowRun {run_id} is actively leased."
                    )

        self._audit.workflow_resumed(
            run_id,
            resume_version=self._workflow_service.get_workflow_run_version(run_id),
        )
        self._notify_runnable(run_id)
        return context

    def execute_claimed_run(
        self,
        run_id: str,
        *,
        worker_id: str,
        lease_guard: LeaseGuard,
    ) -> WorkflowContext:
        """Execute a run that has already been claimed by worker_id."""
        context = self._load_context(run_id)
        workflow_run = context.workflow_run

        if workflow_run.is_terminal:
            return context

        if workflow_run.status == WorkflowStatus.PAUSED:
            raise RuntimeError(
                "PAUSED WorkflowRun resume is outside PF-04 durable execution scope."
            )

        resume_version = self._workflow_service.get_workflow_run_version(run_id)
        task_results = self._workflow_service.get_task_results(run_id)
        recovered_tasks = recover_interrupted_running_tasks(
            workflow_run,
            task_results,
        )

        persister = WorkflowRuntimePersister(
            workflow_service=self._workflow_service,
            audit=self._audit,
            run_id=run_id,
            initial_version=resume_version,
            task_results=task_results,
            lease_guard=lease_guard,
        )

        for task in recovered_tasks:
            context.current_task = task
            if task.status == TaskStatus.FAILED:
                persister.on_task_finished(
                    context,
                    error=RuntimeError(INTERRUPTED_RUNNING_TASK_REASON),
                )

        return self._execute(context, persister, lease_guard=lease_guard)

    def start_research(
        self,
        project: Project,
        workflow_template: WorkflowTemplate,
        *,
        run_id: str | None = None,
    ) -> WorkflowContext:
        """Backward-compatible synchronous path for non-worker callers."""
        context = self.submit_research(
            project,
            workflow_template,
            run_id=run_id,
        )
        if self._execution_port is None:
            persister = WorkflowRuntimePersister(
                workflow_service=self._workflow_service,
                audit=self._audit,
                run_id=context.workflow_run.id,
                initial_version=0,
            )
            return self._execute(context, persister)
        raise RuntimeError(
            "Use submit_research() and WorkerExecutionService for background execution."
        )

    def resume_research(self, run_id: str) -> WorkflowContext:
        """Backward-compatible synchronous resume for non-worker callers."""
        context = self.submit_resume(run_id)
        if context.workflow_run.is_terminal:
            return context
        if self._execution_port is None:
            return self.execute_claimed_run(
                run_id,
                worker_id="inline",
                lease_guard=LeaseGuard(),
            )
        raise RuntimeError(
            "Use submit_resume() and WorkerExecutionService for background execution."
        )

    def _load_context(self, run_id: str) -> WorkflowContext:
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
        if self._context_service_resolver is not None:
            context.services.update(self._context_service_resolver.resolve(context))
        return context

    def _execute(
        self,
        context: WorkflowContext,
        persister: WorkflowRuntimePersister,
        *,
        lease_guard: LeaseGuard | None = None,
    ) -> WorkflowContext:
        if lease_guard is not None:
            lease_guard.validate()
        return self._workflow_engine.run(
            context,
            checkpoint=persister,
        )

    def _notify_runnable(self, run_id: str) -> None:
        if self._run_queue is not None:
            try:
                self._run_queue.notify_runnable(run_id)
            except Exception:
                pass

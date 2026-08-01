from __future__ import annotations

from application.persistence.records import ArtifactRecord, ExecutionLogEntry
from domain.project import Project
from domain.workflow_run import WorkflowRun

from api.schemas.artifacts import ArtifactResponse
from api.schemas.projects import ProjectResponse
from api.schemas.workflow_runs import (
    ExecutionLogResponse,
    StartResearchResponse,
    TaskResponse,
    TaskResultItem,
    WorkflowRunResponse,
)


def project_to_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        status=project.status,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def workflow_run_to_response(
    workflow_run: WorkflowRun,
    *,
    version: int | None = None,
) -> WorkflowRunResponse:
    return WorkflowRunResponse(
        id=workflow_run.id,
        project_id=workflow_run.project_id,
        workflow_template_id=workflow_run.workflow_template_id,
        status=workflow_run.status.value,
        version=version,
        is_terminal=workflow_run.is_terminal,
        tasks=[task_to_response(task) for task in workflow_run.tasks],
    )


def task_to_response(task) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        definition_id=task.definition_id,
        name=task.name,
        status=task.status.value,
        executor_id=task.executor_id,
        executor_type=task.executor_type.value,
        depends_on=list(task.depends_on),
    )


def start_research_to_response(
    workflow_run: WorkflowRun,
) -> StartResearchResponse:
    return StartResearchResponse(
        run_id=workflow_run.id,
        project_id=workflow_run.project_id,
        workflow_template_id=workflow_run.workflow_template_id,
        status=workflow_run.status.value,
        is_terminal=workflow_run.is_terminal,
        tasks=[task_to_response(task) for task in workflow_run.tasks],
    )


def task_results_to_response(
    run_id: str,
    task_results: dict,
) -> list[TaskResultItem]:
    items: list[TaskResultItem] = []
    for task_id, snapshot in task_results.items():
        if isinstance(snapshot, dict):
            items.append(TaskResultItem(task_id=task_id, snapshot=snapshot))
    return items


def execution_log_to_response(entry: ExecutionLogEntry) -> ExecutionLogResponse:
    return ExecutionLogResponse(
        event_id=entry.event_id,
        run_id=entry.run_id,
        event_type=entry.event_type,
        timestamp=entry.timestamp,
        task_id=entry.task_id,
        payload=dict(entry.payload),
    )


def artifact_to_response(artifact: ArtifactRecord) -> ArtifactResponse:
    preview = artifact.content[:200] if artifact.content else ""
    return ArtifactResponse(
        id=artifact.id,
        project_id=artifact.project_id,
        run_id=artifact.run_id,
        artifact_type=artifact.artifact_type,
        title=artifact.title,
        status=artifact.status,
        version=artifact.version,
        content_preview=preview,
    )

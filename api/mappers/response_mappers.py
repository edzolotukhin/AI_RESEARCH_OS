from __future__ import annotations

from application.persistence.records import ArtifactRecord, ExecutionLogEntry, ResearchSubmissionRecord
from domain.project import Project
from domain.planning.research_design import ResearchDesign
from domain.research_brief import ResearchBrief
from domain.workflow_run import WorkflowRun

from api.mappers.research_brief_mappers import research_brief_to_response
from api.mappers.research_design_mappers import research_design_to_response
from api.schemas.artifacts import ArtifactResponse
from api.schemas.projects import ProjectResponse
from api.schemas.workflow_runs import (
    ExecutionLogResponse,
    ExternalSubmissionMetadata,
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


def external_submission_to_response(
    submission: ResearchSubmissionRecord | None,
    *,
    external_request_id: str | None = None,
) -> ExternalSubmissionMetadata | None:
    if submission is None and external_request_id is None:
        return None
    if submission is None:
        return ExternalSubmissionMetadata(external_request_id=external_request_id)
    return ExternalSubmissionMetadata(
        correlation_id=submission.correlation_id,
        external_request_id=external_request_id or submission.idempotency_key,
        source=submission.source,
        submitted_at=submission.created_at.isoformat(),
    )


def workflow_run_to_response(
    workflow_run: WorkflowRun,
    *,
    version: int | None = None,
    results_available: bool = False,
    artifacts_available: bool = False,
    artifact_count: int = 0,
    reports_available: bool = False,
    report_count: int = 0,
    sources_available: bool = False,
    source_count: int = 0,
    evidence_available: bool = False,
    evidence_count: int = 0,
    findings_available: bool = False,
    finding_count: int = 0,
    insights_available: bool = False,
    insight_count: int = 0,
    submission: ResearchSubmissionRecord | None = None,
    research_brief: ResearchBrief | None = None,
    research_design: ResearchDesign | None = None,
) -> WorkflowRunResponse:
    return WorkflowRunResponse(
        id=workflow_run.id,
        project_id=workflow_run.project_id,
        workflow_template_id=workflow_run.workflow_template_id,
        status=workflow_run.status.value,
        version=version,
        is_terminal=workflow_run.is_terminal,
        tasks=[task_to_response(task) for task in workflow_run.tasks],
        results_available=results_available,
        artifacts_available=artifacts_available,
        artifact_count=artifact_count,
        reports_available=reports_available,
        report_count=report_count,
        sources_available=sources_available,
        source_count=source_count,
        evidence_available=evidence_available,
        evidence_count=evidence_count,
        findings_available=findings_available,
        finding_count=finding_count,
        insights_available=insights_available,
        insight_count=insight_count,
        external=external_submission_to_response(submission),
        research_brief=research_brief_to_response(research_brief),
        research_design=research_design_to_response(research_design),
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
    *,
    idempotent_replay: bool = False,
    submission: ResearchSubmissionRecord | None = None,
    external_request_id: str | None = None,
    research_brief: ResearchBrief | None = None,
    research_design: ResearchDesign | None = None,
) -> StartResearchResponse:
    return StartResearchResponse(
        run_id=workflow_run.id,
        project_id=workflow_run.project_id,
        workflow_template_id=workflow_run.workflow_template_id,
        status=workflow_run.status.value,
        is_terminal=workflow_run.is_terminal,
        tasks=[task_to_response(task) for task in workflow_run.tasks],
        idempotent_replay=idempotent_replay,
        external=external_submission_to_response(
            submission,
            external_request_id=external_request_id,
        ),
        research_brief=research_brief_to_response(research_brief),
        research_design=research_design_to_response(research_design),
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
        payload=dict(entry.payload or {}),
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
        media_type=artifact.media_type,
        filename=artifact.filename,
        content_checksum=artifact.content_checksum,
        report_id=artifact.report_id,
        content_preview=preview,
    )

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, Header, Query, Response, status
from fastapi.responses import JSONResponse

from api.dependencies import (
    AgencyDep,
    ArtifactServiceDep,
    ContainerDep,
    ExecutionLogServiceDep,
    WorkflowServiceDep,
)
from application.persistence.exceptions import DuplicateEntityError, EntityNotFoundError
from application.runtime.background_execution_capability import (
    requires_http_background_submission,
)
from application.runtime.research_request_fingerprint import (
    compute_research_request_fingerprint,
)
from api.mappers.response_mappers import (
    execution_log_to_response,
    external_submission_to_response,
    start_research_to_response,
    task_results_to_response,
    workflow_run_to_response,
)
from api.schemas.workflow_runs import (
    ExecutionLogListResponse,
    StartResearchRequest,
    StartResearchResponse,
    WorkflowRunListResponse,
    WorkflowRunResponse,
    WorkflowRunResultsResponse,
)
from domain.project_brief import ProjectBrief
from domain.workflow_status import WorkflowStatus

router = APIRouter(tags=["workflow-runs"])
logger = logging.getLogger(__name__)

MAX_LOG_LIMIT = 1000


@router.post(
    "/projects/{project_id}/research",
    response_model=StartResearchResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit research for background execution",
    operation_id="startResearch",
    description=(
        "Validates the request and runs planning synchronously in the API "
        "process. Persists WorkflowTemplate and WorkflowRun, submits the run "
        "for background worker execution, and returns 202 Accepted. "
        "WorkflowEngine execution occurs only in the worker. Poll "
        "GET /workflow-runs/{run_id} until is_terminal is true. "
        "Supply Idempotency-Key to deduplicate external orchestrator retries."
    ),
    responses={
        404: {"description": "Project not found."},
        409: {
            "description": (
                "Background execution unavailable, idempotency conflict, or "
                "resume conflict."
            ),
        },
        422: {"description": "Missing or invalid project brief."},
    },
)
def start_research(
    project_id: str,
    body: StartResearchRequest,
    agency: AgencyDep,
    container: ContainerDep,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
) -> StartResearchResponse:
    if container.background_execution is not None:
        requires_http_background_submission(container.background_execution)

    correlation_id = body.correlation_id or x_correlation_id
    source = body.source
    request_id = str(uuid4())
    fingerprint = compute_research_request_fingerprint(
        project_id=project_id,
        brief=body.brief.model_dump(mode="json"),
    )

    submission_service = container.research_submission_service
    submission_result = None
    if submission_service is not None:
        submission_result = submission_service.resolve_submission(
            project_id=project_id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            correlation_id=correlation_id,
            source=source,
        )
        if submission_result.replay:
            existing = container.workflow_service.get_workflow_run(
                submission_result.run_id,
            )
            payload = start_research_to_response(
                existing,
                idempotent_replay=True,
                submission=submission_result.submission,
                external_request_id=idempotency_key,
            )
            response.headers["Location"] = f"/workflow-runs/{payload.run_id}"
            logger.info(
                "research_submission_replayed",
                extra={
                    "request_id": request_id,
                    "correlation_id": correlation_id,
                    "route": "startResearch",
                    "status": 202,
                    "run_id": payload.run_id,
                    "source": source,
                },
            )
            return payload

        try:
            existing = container.workflow_service.get_workflow_run(
                submission_result.run_id,
            )
        except EntityNotFoundError:
            existing = None
        if existing is not None:
            submission_service.mark_completed(
                project_id=project_id,
                idempotency_key=idempotency_key,
            )
            payload = start_research_to_response(
                existing,
                idempotent_replay=not submission_result.created,
                submission=submission_result.submission,
                external_request_id=idempotency_key,
            )
            response.headers["Location"] = f"/workflow-runs/{payload.run_id}"
            logger.info(
                "research_submission_replayed",
                extra={
                    "request_id": request_id,
                    "correlation_id": correlation_id,
                    "route": "startResearch",
                    "status": 202,
                    "run_id": payload.run_id,
                    "source": source,
                },
            )
            return payload

    project = agency.get_project(project_id)
    project.brief = ProjectBrief(
        client=body.brief.client,
        project_title=body.brief.project_title,
        business_problem=body.brief.business_problem,
        research_goal=body.brief.research_goal,
        research_objectives=list(body.brief.research_objectives),
        research_object=body.brief.research_object,
        target_audience=body.brief.target_audience,
        geography=body.brief.geography,
        constraints=list(body.brief.constraints),
        timeline=body.brief.timeline,
        comments=body.brief.comments,
    )

    run_id = submission_result.run_id if submission_result is not None else None
    try:
        context = agency.start_research(project, run_id=run_id)
    except DuplicateEntityError:
        if (
            submission_service is not None
            and idempotency_key
            and run_id is not None
        ):
            existing = container.workflow_service.get_workflow_run(run_id)
            submission_service.mark_completed(
                project_id=project_id,
                idempotency_key=idempotency_key,
            )
            payload = start_research_to_response(
                existing,
                idempotent_replay=True,
                submission=submission_result.submission if submission_result else None,
                external_request_id=idempotency_key,
            )
            response.headers["Location"] = f"/workflow-runs/{payload.run_id}"
            logger.info(
                "research_submission_replayed",
                extra={
                    "request_id": request_id,
                    "correlation_id": correlation_id,
                    "route": "startResearch",
                    "status": 202,
                    "run_id": payload.run_id,
                    "source": source,
                },
            )
            return payload
        raise
    except Exception:
        if (
            submission_service is not None
            and idempotency_key
            and submission_result is not None
            and not submission_result.created
            and run_id is not None
        ):
            try:
                existing = container.workflow_service.get_workflow_run(run_id)
            except EntityNotFoundError:
                existing = None
            if existing is not None:
                submission_service.mark_completed(
                    project_id=project_id,
                    idempotency_key=idempotency_key,
                )
                payload = start_research_to_response(
                    existing,
                    idempotent_replay=True,
                    submission=submission_result.submission,
                    external_request_id=idempotency_key,
                )
                response.headers["Location"] = f"/workflow-runs/{payload.run_id}"
                logger.info(
                    "research_submission_replayed",
                    extra={
                        "request_id": request_id,
                        "correlation_id": correlation_id,
                        "route": "startResearch",
                        "status": 202,
                        "run_id": payload.run_id,
                        "source": source,
                    },
                )
                return payload
        if (
            submission_service is not None
            and idempotency_key
            and submission_result is not None
            and submission_result.created
        ):
            submission_service.rollback_submission(
                project_id=project_id,
                idempotency_key=idempotency_key,
            )
        raise

    if submission_service is not None and idempotency_key:
        submission_service.mark_completed(
            project_id=project_id,
            idempotency_key=idempotency_key,
        )

    payload = start_research_to_response(
        context.workflow_run,
        idempotent_replay=False,
        submission=submission_result.submission if submission_result else None,
        external_request_id=idempotency_key,
    )
    response.headers["Location"] = f"/workflow-runs/{payload.run_id}"
    logger.info(
        "research_submitted",
        extra={
            "request_id": request_id,
            "correlation_id": correlation_id,
            "route": "startResearch",
            "status": 202,
            "run_id": payload.run_id,
            "source": source,
        },
    )
    return payload


@router.get(
    "/workflow-runs/{run_id}",
    response_model=WorkflowRunResponse,
    summary="Get a workflow run",
    operation_id="getWorkflowRun",
    description=(
        "Poll workflow run status until is_terminal is true. Safe for repeated "
        "external orchestrator polling."
    ),
    responses={404: {"description": "Workflow run not found."}},
)
def get_workflow_run(
    run_id: str,
    workflow_service: WorkflowServiceDep,
    artifact_service: ArtifactServiceDep,
    container: ContainerDep,
) -> WorkflowRunResponse:
    workflow_run = workflow_service.get_workflow_run(run_id)
    version = None
    try:
        version = workflow_service.get_workflow_run_version(run_id)
    except Exception:
        version = None
    task_results = workflow_service.get_task_results(run_id)
    artifacts = artifact_service.list_artifacts_for_run(run_id)
    submission = None
    if container.research_submission_service is not None:
        submission = container.research_submission_service.get_submission_for_run(
            run_id,
        )
    return workflow_run_to_response(
        workflow_run,
        version=version,
        results_available=bool(task_results),
        artifacts_available=bool(artifacts),
        submission=submission,
    )


@router.get(
    "/projects/{project_id}/workflow-runs",
    response_model=WorkflowRunListResponse,
    summary="List workflow runs for a project",
    operation_id="listWorkflowRunsForProject",
)
def list_workflow_runs_for_project(
    project_id: str,
    workflow_service: WorkflowServiceDep,
    artifact_service: ArtifactServiceDep,
    container: ContainerDep,
    status_filter: WorkflowStatus | None = Query(default=None, alias="status"),
) -> WorkflowRunListResponse:
    runs = workflow_service.list_workflow_runs_for_project(
        project_id,
        status=status_filter,
    )
    items = []
    for workflow_run in runs:
        version = None
        try:
            version = workflow_service.get_workflow_run_version(workflow_run.id)
        except Exception:
            version = None
        task_results = workflow_service.get_task_results(workflow_run.id)
        artifacts = artifact_service.list_artifacts_for_run(workflow_run.id)
        submission = None
        if container.research_submission_service is not None:
            submission = container.research_submission_service.get_submission_for_run(
                workflow_run.id,
            )
        items.append(
            workflow_run_to_response(
                workflow_run,
                version=version,
                results_available=bool(task_results),
                artifacts_available=bool(artifacts),
                submission=submission,
            )
        )
    return WorkflowRunListResponse(items=items, count=len(items))


@router.post(
    "/workflow-runs/{run_id}/resume",
    response_model=WorkflowRunResponse,
    summary="Submit workflow run resume for background execution",
    operation_id="resumeWorkflowRun",
    responses={
        404: {"description": "Workflow run not found."},
        409: {"description": "Resume unavailable for PAUSED runs, active lease, or non-durable backend."},
    },
)
def resume_workflow_run(
    run_id: str,
    agency: AgencyDep,
    container: ContainerDep,
    workflow_service: WorkflowServiceDep,
    artifact_service: ArtifactServiceDep,
    response: Response,
) -> WorkflowRunResponse | JSONResponse:
    if container.background_execution is not None:
        requires_http_background_submission(container.background_execution)

    workflow_run = workflow_service.get_workflow_run(run_id)
    if workflow_run.is_terminal:
        version = None
        try:
            version = workflow_service.get_workflow_run_version(run_id)
        except Exception:
            version = None
        task_results = workflow_service.get_task_results(run_id)
        artifacts = artifact_service.list_artifacts_for_run(run_id)
        submission = None
        if container.research_submission_service is not None:
            submission = container.research_submission_service.get_submission_for_run(
                run_id,
            )
        return workflow_run_to_response(
            workflow_run,
            version=version,
            results_available=bool(task_results),
            artifacts_available=bool(artifacts),
            submission=submission,
        )

    context = agency.submit_resume(run_id)
    task_results = workflow_service.get_task_results(run_id)
    artifacts = artifact_service.list_artifacts_for_run(run_id)
    submission = None
    if container.research_submission_service is not None:
        submission = container.research_submission_service.get_submission_for_run(
            run_id,
        )
    payload = workflow_run_to_response(
        context.workflow_run,
        version=None,
        results_available=bool(task_results),
        artifacts_available=bool(artifacts),
        submission=submission,
    )
    response.status_code = status.HTTP_202_ACCEPTED
    response.headers["Location"] = f"/workflow-runs/{run_id}"
    return payload


@router.get(
    "/workflow-runs/{run_id}/results",
    response_model=WorkflowRunResultsResponse,
    summary="Get durable task results for a workflow run",
    operation_id="getWorkflowRunResults",
    description=(
        "Returns task result snapshots when available. results_ready is true only "
        "when the workflow run is terminal."
    ),
    responses={404: {"description": "Workflow run not found."}},
)
def get_workflow_run_results(
    run_id: str,
    workflow_service: WorkflowServiceDep,
) -> WorkflowRunResultsResponse:
    workflow_run = workflow_service.get_workflow_run(run_id)
    task_results = workflow_service.get_task_results(run_id)
    results_ready = workflow_run.is_terminal
    return WorkflowRunResultsResponse(
        run_id=run_id,
        status=workflow_run.status.value,
        is_terminal=workflow_run.is_terminal,
        results_ready=results_ready,
        task_results=task_results_to_response(run_id, task_results),
    )


@router.get(
    "/workflow-runs/{run_id}/logs",
    response_model=ExecutionLogListResponse,
    summary="Get append-only execution logs for a workflow run",
    operation_id="getWorkflowRunLogs",
    responses={404: {"description": "Workflow run not found."}},
)
def get_workflow_run_logs(
    run_id: str,
    workflow_service: WorkflowServiceDep,
    execution_log_service: ExecutionLogServiceDep,
    limit: int = Query(default=MAX_LOG_LIMIT, ge=1, le=MAX_LOG_LIMIT),
) -> ExecutionLogListResponse:
    workflow_service.get_workflow_run(run_id)
    logs = execution_log_service.list_logs_for_run(run_id)
    bounded = logs[:limit]
    return ExecutionLogListResponse(
        items=[execution_log_to_response(entry) for entry in bounded],
        count=len(bounded),
    )

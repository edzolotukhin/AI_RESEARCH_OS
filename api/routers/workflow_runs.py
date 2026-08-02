from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Query, Response, status
from fastapi.responses import JSONResponse

from api.auth import AuthorizationDep, PrincipalDep, bearer_scheme
from api.dependencies import (
    AgencyDep,
    ArtifactServiceDep,
    ContainerDep,
    ExecutionLogServiceDep,
    WorkflowServiceDep,
)
from application.persistence.exceptions import (
    ConcurrentModificationError,
    DuplicateEntityError,
    EntityNotFoundError,
)
from application.research.brief_normalizer import normalize_research_brief_payload
from application.research.brief_validator import validate_research_brief
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
from domain.workflow_status import WorkflowStatus

router = APIRouter(tags=["workflow-runs"])
logger = logging.getLogger(__name__)

MAX_LOG_LIMIT = 1000


def _brief_snapshot_for_template(workflow_service, workflow_template_id: str):
    try:
        template = workflow_service.get_template(workflow_template_id)
    except Exception:
        return None
    return template.research_brief_snapshot


def _design_snapshot_for_template(workflow_service, workflow_template_id: str):
    try:
        template = workflow_service.get_template(workflow_template_id)
    except Exception:
        return None
    return template.research_design_snapshot


def _brief_snapshot_for_run(workflow_service, workflow_run):
    return _brief_snapshot_for_template(
        workflow_service,
        workflow_run.workflow_template_id,
    )


def _design_snapshot_for_run(workflow_service, workflow_run):
    return _design_snapshot_for_template(
        workflow_service,
        workflow_run.workflow_template_id,
    )


def _log_research_response(
    *,
    logger: logging.Logger,
    event: str,
    request_id: str,
    correlation_id: str | None,
    run_id: str,
    source: str | None,
    principal_id: str | None = None,
    api_key_id: str | None = None,
) -> None:
    logger.info(
        event,
        extra={
            "request_id": request_id,
            "correlation_id": correlation_id,
            "route": "startResearch",
            "status": 202,
            "run_id": run_id,
            "source": source,
            "principal_id": principal_id,
            "api_key_id": api_key_id,
        },
    )


def _replay_submission_response(
    *,
    workflow_run,
    response: Response,
    submission,
    idempotency_key: str | None,
    idempotent_replay: bool,
    logger: logging.Logger,
    request_id: str,
    correlation_id: str | None,
    source: str | None,
    workflow_service,
    principal_id: str | None = None,
    api_key_id: str | None = None,
    event: str = "research_submission_replayed",
):
    payload = start_research_to_response(
        workflow_run,
        idempotent_replay=idempotent_replay,
        submission=submission,
        external_request_id=idempotency_key,
        research_brief=_brief_snapshot_for_run(workflow_service, workflow_run),
        research_design=_design_snapshot_for_run(workflow_service, workflow_run),
    )
    response.headers["Location"] = f"/workflow-runs/{payload.run_id}"
    _log_research_response(
        logger=logger,
        event=event,
        request_id=request_id,
        correlation_id=correlation_id,
        run_id=payload.run_id,
        source=source,
        principal_id=principal_id,
        api_key_id=api_key_id,
    )
    return payload


def _resolve_idempotent_replay(
    *,
    submission_service,
    container,
    submission_result,
    project_id: str,
    idempotency_key: str,
    response: Response,
    logger: logging.Logger,
    request_id: str,
    correlation_id: str | None,
    source: str | None,
    principal_id: str | None = None,
    api_key_id: str | None = None,
):
    if submission_result.replay:
        existing = container.workflow_service.get_workflow_run(
            submission_result.run_id,
        )
        return _replay_submission_response(
            workflow_run=existing,
            response=response,
            submission=submission_result.submission,
            idempotency_key=idempotency_key,
            idempotent_replay=True,
            logger=logger,
            request_id=request_id,
            correlation_id=correlation_id,
            source=source,
            workflow_service=container.workflow_service,
            principal_id=principal_id,
            api_key_id=api_key_id,
        )

    load_run = container.workflow_service.get_workflow_run
    existing = submission_service.resolve_visible_run(
        project_id=project_id,
        idempotency_key=idempotency_key,
        run_id=submission_result.run_id,
        load_workflow_run=load_run,
    )
    if existing is not None:
        return _replay_submission_response(
            workflow_run=existing,
            response=response,
            submission=submission_result.submission,
            idempotency_key=idempotency_key,
            idempotent_replay=not submission_result.created,
            logger=logger,
            request_id=request_id,
            correlation_id=correlation_id,
            source=source,
            workflow_service=container.workflow_service,
            principal_id=principal_id,
            api_key_id=api_key_id,
        )

    if not submission_result.created:
        peer_run = submission_service.wait_for_peer_completion(
            project_id=project_id,
            idempotency_key=idempotency_key,
            run_id=submission_result.run_id,
            load_workflow_run=load_run,
        )
        if peer_run is not None:
            return _replay_submission_response(
                workflow_run=peer_run,
                response=response,
                submission=submission_result.submission,
                idempotency_key=idempotency_key,
                idempotent_replay=True,
                logger=logger,
                request_id=request_id,
                correlation_id=correlation_id,
                source=source,
                workflow_service=container.workflow_service,
                principal_id=principal_id,
                api_key_id=api_key_id,
            )

    return None


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
        401: {"description": "Authentication required."},
        404: {"description": "Project not found."},
        409: {
            "description": (
                "Background execution unavailable, idempotency conflict, or "
                "resume conflict."
            ),
        },
        422: {"description": "Missing or invalid project brief."},
    },
    dependencies=[Depends(bearer_scheme)],
)
def start_research(
    project_id: str,
    body: StartResearchRequest,
    agency: AgencyDep,
    container: ContainerDep,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
) -> StartResearchResponse:
    if container.background_execution is not None:
        requires_http_background_submission(container.background_execution)

    project = authorization.require_project(principal, project_id)

    correlation_id = body.correlation_id or x_correlation_id
    source = body.source
    request_id = str(uuid4())

    research_brief = normalize_research_brief_payload(
        body.brief.model_dump(mode="json"),
    )
    validate_research_brief(research_brief)

    fingerprint = compute_research_request_fingerprint(
        project_id=project_id,
        brief=research_brief.to_fingerprint_dict(),
    )

    submission_service = container.research_submission_service
    submission_result = None
    if submission_service is not None and idempotency_key:
        submission_result = submission_service.resolve_submission(
            project_id=project_id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            correlation_id=correlation_id,
            source=source,
        )
        replay_response = _resolve_idempotent_replay(
            submission_service=submission_service,
            container=container,
            submission_result=submission_result,
            project_id=project_id,
            idempotency_key=idempotency_key,
            response=response,
            logger=logger,
            request_id=request_id,
            correlation_id=correlation_id,
            source=source,
            principal_id=principal.principal_id,
            api_key_id=principal.api_key_id,
        )
        if replay_response is not None:
            return replay_response

    project.research_brief = research_brief

    run_id = submission_result.run_id if submission_result is not None else None
    try:
        context = agency.start_research(project, run_id=run_id)
    except (DuplicateEntityError, ConcurrentModificationError):
        if (
            submission_service is not None
            and idempotency_key
            and submission_result is not None
            and run_id is not None
        ):
            existing = submission_service.resolve_visible_run(
                project_id=project_id,
                idempotency_key=idempotency_key,
                run_id=run_id,
                load_workflow_run=container.workflow_service.get_workflow_run,
            )
            if existing is None and not submission_result.created:
                existing = submission_service.wait_for_peer_completion(
                    project_id=project_id,
                    idempotency_key=idempotency_key,
                    run_id=run_id,
                    load_workflow_run=container.workflow_service.get_workflow_run,
                )
            if existing is not None:
                return _replay_submission_response(
                    workflow_run=existing,
                    response=response,
                    submission=submission_result.submission,
                    idempotency_key=idempotency_key,
                    idempotent_replay=True,
                    logger=logger,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    source=source,
                    workflow_service=container.workflow_service,
                    principal_id=principal.principal_id,
                    api_key_id=principal.api_key_id,
                )
        raise
    except Exception:
        if (
            submission_service is not None
            and idempotency_key
            and submission_result is not None
            and not submission_result.created
            and run_id is not None
        ):
            existing = submission_service.resolve_visible_run(
                project_id=project_id,
                idempotency_key=idempotency_key,
                run_id=run_id,
                load_workflow_run=container.workflow_service.get_workflow_run,
            )
            if existing is not None:
                return _replay_submission_response(
                    workflow_run=existing,
                    response=response,
                    submission=submission_result.submission,
                    idempotency_key=idempotency_key,
                    idempotent_replay=True,
                    logger=logger,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    source=source,
                    workflow_service=container.workflow_service,
                    principal_id=principal.principal_id,
                    api_key_id=principal.api_key_id,
                )
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

    design_snapshot = None
    if context.workflow_template is not None:
        design_snapshot = context.workflow_template.research_design_snapshot

    payload = start_research_to_response(
        context.workflow_run,
        idempotent_replay=False,
        submission=submission_result.submission if submission_result else None,
        external_request_id=idempotency_key,
        research_brief=research_brief,
        research_design=design_snapshot,
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
            "principal_id": principal.principal_id,
            "api_key_id": principal.api_key_id,
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
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Workflow run not found."},
    },
)
def get_workflow_run(
    run_id: str,
    workflow_service: WorkflowServiceDep,
    artifact_service: ArtifactServiceDep,
    container: ContainerDep,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
) -> WorkflowRunResponse:
    workflow_run, _ = authorization.require_run(principal, run_id)
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
        research_brief=_brief_snapshot_for_run(workflow_service, workflow_run),
        research_design=_design_snapshot_for_run(workflow_service, workflow_run),
    )


@router.get(
    "/projects/{project_id}/workflow-runs",
    response_model=WorkflowRunListResponse,
    summary="List workflow runs for a project",
    operation_id="listWorkflowRunsForProject",
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Project not found."},
    },
)
def list_workflow_runs_for_project(
    project_id: str,
    workflow_service: WorkflowServiceDep,
    artifact_service: ArtifactServiceDep,
    container: ContainerDep,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
    status_filter: WorkflowStatus | None = Query(default=None, alias="status"),
) -> WorkflowRunListResponse:
    authorization.require_project(principal, project_id)
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
                research_brief=_brief_snapshot_for_run(workflow_service, workflow_run),
                research_design=_design_snapshot_for_run(workflow_service, workflow_run),
            )
        )
    return WorkflowRunListResponse(items=items, count=len(items))


@router.post(
    "/workflow-runs/{run_id}/resume",
    response_model=WorkflowRunResponse,
    summary="Submit workflow run resume for background execution",
    operation_id="resumeWorkflowRun",
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
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
    authorization: AuthorizationDep,
    principal: PrincipalDep,
    response: Response,
) -> WorkflowRunResponse | JSONResponse:
    if container.background_execution is not None:
        requires_http_background_submission(container.background_execution)

    workflow_run, _ = authorization.require_run(principal, run_id)
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
            research_brief=_brief_snapshot_for_run(workflow_service, workflow_run),
            research_design=_design_snapshot_for_run(workflow_service, workflow_run),
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
        research_brief=_brief_snapshot_for_run(workflow_service, context.workflow_run),
        research_design=_design_snapshot_for_run(workflow_service, context.workflow_run),
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
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Workflow run not found."},
    },
)
def get_workflow_run_results(
    run_id: str,
    workflow_service: WorkflowServiceDep,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
) -> WorkflowRunResultsResponse:
    workflow_run, _ = authorization.require_run(principal, run_id)
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
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Workflow run not found."},
    },
)
def get_workflow_run_logs(
    run_id: str,
    execution_log_service: ExecutionLogServiceDep,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
    limit: int = Query(default=100, ge=1, le=MAX_LOG_LIMIT),
) -> ExecutionLogListResponse:
    authorization.require_run(principal, run_id)
    logs = execution_log_service.list_logs_for_run(run_id)
    bounded = logs[:limit]
    return ExecutionLogListResponse(
        items=[execution_log_to_response(entry) for entry in bounded],
        count=len(bounded),
    )

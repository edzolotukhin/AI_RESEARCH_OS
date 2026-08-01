from __future__ import annotations

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import JSONResponse

from api.dependencies import (
    AgencyDep,
    ContainerDep,
    ExecutionLogServiceDep,
    WorkflowServiceDep,
)
from application.runtime.background_execution_capability import (
    requires_http_background_submission,
)
from api.mappers.response_mappers import (
    execution_log_to_response,
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
        "GET /workflow-runs/{run_id} for progress. Planning latency affects "
        "the HTTP response time."
    ),
    responses={
        404: {"description": "Project not found."},
        409: {"description": "Background durable execution unavailable for this backend."},
        422: {"description": "Missing or invalid project brief."},
    },
)
def start_research(
    project_id: str,
    body: StartResearchRequest,
    agency: AgencyDep,
    container: ContainerDep,
    response: Response,
) -> StartResearchResponse:
    if container.background_execution is not None:
        requires_http_background_submission(container.background_execution)
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
    context = agency.start_research(project)
    payload = start_research_to_response(context.workflow_run)
    response.headers["Location"] = f"/workflow-runs/{payload.run_id}"
    return payload


@router.get(
    "/workflow-runs/{run_id}",
    response_model=WorkflowRunResponse,
    summary="Get a workflow run",
    operation_id="getWorkflowRun",
    responses={404: {"description": "Workflow run not found."}},
)
def get_workflow_run(
    run_id: str,
    workflow_service: WorkflowServiceDep,
) -> WorkflowRunResponse:
    workflow_run = workflow_service.get_workflow_run(run_id)
    version = None
    try:
        version = workflow_service.get_workflow_run_version(run_id)
    except Exception:
        version = None
    return workflow_run_to_response(workflow_run, version=version)


@router.get(
    "/projects/{project_id}/workflow-runs",
    response_model=WorkflowRunListResponse,
    summary="List workflow runs for a project",
    operation_id="listWorkflowRunsForProject",
)
def list_workflow_runs_for_project(
    project_id: str,
    workflow_service: WorkflowServiceDep,
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
        items.append(workflow_run_to_response(workflow_run, version=version))
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
        return workflow_run_to_response(workflow_run, version=version)

    context = agency.submit_resume(run_id)
    payload = workflow_run_to_response(context.workflow_run, version=None)
    response.status_code = status.HTTP_202_ACCEPTED
    response.headers["Location"] = f"/workflow-runs/{run_id}"
    return payload


@router.get(
    "/workflow-runs/{run_id}/results",
    response_model=WorkflowRunResultsResponse,
    summary="Get durable task results for a workflow run",
    operation_id="getWorkflowRunResults",
    responses={404: {"description": "Workflow run not found."}},
)
def get_workflow_run_results(
    run_id: str,
    workflow_service: WorkflowServiceDep,
) -> WorkflowRunResultsResponse:
    workflow_service.get_workflow_run(run_id)
    task_results = workflow_service.get_task_results(run_id)
    return WorkflowRunResultsResponse(
        run_id=run_id,
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

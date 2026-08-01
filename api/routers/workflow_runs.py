from __future__ import annotations

from fastapi import APIRouter, Query, status

from api.dependencies import (
    AgencyDep,
    ExecutionLogServiceDep,
    WorkflowServiceDep,
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
    status_code=status.HTTP_200_OK,
    summary="Start research for a project (synchronous)",
    operation_id="startResearch",
    description=(
        "Executes planning and workflow runtime synchronously in the request "
        "process. Returns 200 with the terminal or current run state when "
        "complete; does not return 202 and does not continue in a background "
        "worker if the client disconnects. Live planning requires OPENAI_API_KEY."
    ),
    responses={
        404: {"description": "Project not found."},
        422: {"description": "Missing or invalid project brief."},
    },
)
def start_research(
    project_id: str,
    body: StartResearchRequest,
    agency: AgencyDep,
) -> StartResearchResponse:
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
    return start_research_to_response(context.workflow_run)


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
    summary="Resume a workflow run (synchronous)",
    operation_id="resumeWorkflowRun",
    responses={
        404: {"description": "Workflow run not found."},
        409: {"description": "Resume unavailable for PAUSED runs or non-durable backend."},
    },
)
def resume_workflow_run(
    run_id: str,
    agency: AgencyDep,
    workflow_service: WorkflowServiceDep,
) -> WorkflowRunResponse:
    context = agency.resume_research(run_id)
    version = None
    try:
        version = workflow_service.get_workflow_run_version(run_id)
    except Exception:
        version = None
    return workflow_run_to_response(context.workflow_run, version=version)


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

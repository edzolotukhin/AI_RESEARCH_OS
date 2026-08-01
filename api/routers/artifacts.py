from __future__ import annotations

from fastapi import APIRouter

from api.dependencies import ArtifactServiceDep, WorkflowServiceDep
from api.mappers.response_mappers import artifact_to_response
from api.schemas.artifacts import ArtifactListResponse

router = APIRouter(tags=["artifacts"])


@router.get(
    "/projects/{project_id}/artifacts",
    response_model=ArtifactListResponse,
    summary="List artifact metadata for a project",
    operation_id="listProjectArtifacts",
)
def list_project_artifacts(
    project_id: str,
    artifact_service: ArtifactServiceDep,
) -> ArtifactListResponse:
    artifacts = artifact_service.list_artifacts_for_project(project_id)
    return ArtifactListResponse(
        items=[artifact_to_response(artifact) for artifact in artifacts],
        count=len(artifacts),
    )


@router.get(
    "/workflow-runs/{run_id}/artifacts",
    response_model=ArtifactListResponse,
    summary="List artifact metadata for a workflow run",
    operation_id="listWorkflowRunArtifacts",
    responses={404: {"description": "Workflow run not found."}},
)
def list_workflow_run_artifacts(
    run_id: str,
    artifact_service: ArtifactServiceDep,
    workflow_service: WorkflowServiceDep,
) -> ArtifactListResponse:
    workflow_service.get_workflow_run(run_id)
    artifacts = artifact_service.list_artifacts_for_run(run_id)
    return ArtifactListResponse(
        items=[artifact_to_response(artifact) for artifact in artifacts],
        count=len(artifacts),
    )

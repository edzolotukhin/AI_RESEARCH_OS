from __future__ import annotations

from fastapi import APIRouter, Depends

from api.auth import AuthorizationDep, PrincipalDep, bearer_scheme
from api.dependencies import ArtifactServiceDep
from api.mappers.response_mappers import artifact_to_response
from api.schemas.artifacts import ArtifactContentResponse, ArtifactListResponse, ArtifactResponse

router = APIRouter(tags=["artifacts"])


@router.get(
    "/projects/{project_id}/artifacts",
    response_model=ArtifactListResponse,
    summary="List artifact metadata for a project",
    operation_id="listProjectArtifacts",
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Project not found."},
    },
)
def list_project_artifacts(
    project_id: str,
    artifact_service: ArtifactServiceDep,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
) -> ArtifactListResponse:
    authorization.require_project(principal, project_id)
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
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Workflow run not found."},
    },
)
def list_workflow_run_artifacts(
    run_id: str,
    artifact_service: ArtifactServiceDep,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
) -> ArtifactListResponse:
    authorization.require_run(principal, run_id)
    artifacts = artifact_service.list_artifacts_for_run(run_id)
    return ArtifactListResponse(
        items=[artifact_to_response(artifact) for artifact in artifacts],
        count=len(artifacts),
    )


@router.get(
    "/artifacts/{artifact_id}",
    response_model=ArtifactResponse,
    summary="Get artifact metadata by id",
    operation_id="getArtifact",
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Artifact not found."},
    },
)
def get_artifact(
    artifact_id: str,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
) -> ArtifactResponse:
    artifact, _ = authorization.require_artifact(principal, artifact_id)
    return artifact_to_response(artifact)


@router.get(
    "/artifacts/{artifact_id}/content",
    response_model=ArtifactContentResponse,
    summary="Get durable artifact content",
    operation_id="getArtifactContent",
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Artifact not found."},
    },
)
def get_artifact_content(
    artifact_id: str,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
) -> ArtifactContentResponse:
    artifact, _ = authorization.require_artifact(principal, artifact_id)
    return ArtifactContentResponse(
        id=artifact.id,
        media_type=artifact.media_type,
        filename=artifact.filename,
        content=artifact.content,
        content_checksum=artifact.content_checksum,
    )

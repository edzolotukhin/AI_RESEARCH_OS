from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status

from api.auth import AuthorizationDep, PrincipalDep, bearer_scheme
from api.dependencies import AgencyDep
from api.mappers.response_mappers import project_to_response
from api.schemas.projects import (
    CreateProjectRequest,
    ProjectListResponse,
    ProjectResponse,
)

router = APIRouter(prefix="/projects", tags=["projects"])

MAX_PAGE_LIMIT = 100


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project",
    operation_id="createProject",
    dependencies=[Depends(bearer_scheme)],
    responses={401: {"description": "Authentication required."}},
)
def create_project(
    body: CreateProjectRequest,
    agency: AgencyDep,
    principal: PrincipalDep,
    response: Response,
) -> ProjectResponse:
    project = agency.create_project(
        body.name,
        owner_principal_id=principal.principal_id,
    )
    response.headers["Location"] = f"/projects/{project.id}"
    return project_to_response(project)


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Get a project by ID",
    operation_id="getProject",
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Project not found."},
    },
)
def get_project(
    project_id: str,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
) -> ProjectResponse:
    project = authorization.require_project(principal, project_id)
    return project_to_response(project)


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="List projects",
    operation_id="listProjects",
    dependencies=[Depends(bearer_scheme)],
    responses={401: {"description": "Authentication required."}},
)
def list_projects(
    authorization: AuthorizationDep,
    principal: PrincipalDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_LIMIT),
) -> ProjectListResponse:
    projects = authorization.list_visible_projects(
        principal,
        offset=offset,
        limit=limit,
    )
    return ProjectListResponse(
        items=[project_to_response(project) for project in projects],
        offset=offset,
        limit=limit,
        count=len(projects),
    )

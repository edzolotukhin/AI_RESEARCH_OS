from __future__ import annotations

from fastapi import APIRouter, Query, Response, status

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
)
def create_project(
    body: CreateProjectRequest,
    agency: AgencyDep,
    response: Response,
) -> ProjectResponse:
    project = agency.create_project(body.name)
    response.headers["Location"] = f"/projects/{project.id}"
    return project_to_response(project)


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Get a project by ID",
    operation_id="getProject",
    responses={404: {"description": "Project not found."}},
)
def get_project(project_id: str, agency: AgencyDep) -> ProjectResponse:
    return project_to_response(agency.get_project(project_id))


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="List projects",
    operation_id="listProjects",
)
def list_projects(
    agency: AgencyDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_LIMIT),
) -> ProjectListResponse:
    projects = agency.list_projects(offset=offset, limit=limit)
    return ProjectListResponse(
        items=[project_to_response(project) for project in projects],
        offset=offset,
        limit=limit,
        count=len(projects),
    )

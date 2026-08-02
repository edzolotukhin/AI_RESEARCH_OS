from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.auth import AuthorizationDep, PrincipalDep, bearer_scheme
from api.dependencies import SourceServiceDep
from api.mappers.source_mappers import source_to_response
from api.schemas.sources import SourceListResponse, SourceResponse

router = APIRouter(tags=["sources"])


@router.get(
    "/projects/{project_id}/sources",
    response_model=SourceListResponse,
    summary="List durable research sources for a project",
    operation_id="listProjectSources",
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Project not found."},
    },
)
def list_project_sources(
    project_id: str,
    source_service: SourceServiceDep,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
    research_question_id: str | None = Query(default=None),
    retrieval_status: str | None = Query(default=None),
) -> SourceListResponse:
    authorization.require_project(principal, project_id)
    from domain.sources.retrieval_status import RetrievalStatus

    status = RetrievalStatus(retrieval_status) if retrieval_status else None
    sources = source_service.list_sources_for_project(
        project_id,
        research_question_id=research_question_id,
        retrieval_status=status,
    )
    return SourceListResponse(
        items=[source_to_response(source) for source in sources],
        count=len(sources),
    )


@router.get(
    "/sources/{source_id}",
    response_model=SourceResponse,
    summary="Get a durable research source by id",
    operation_id="getSource",
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Source not found."},
    },
)
def get_source(
    source_id: str,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
) -> SourceResponse:
    source, _ = authorization.require_source(principal, source_id)
    return source_to_response(source)

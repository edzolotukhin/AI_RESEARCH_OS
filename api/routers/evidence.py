from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.auth import AuthorizationDep, PrincipalDep, bearer_scheme
from api.dependencies import EvidenceServiceDep
from api.mappers.evidence_mappers import evidence_to_response
from api.schemas.evidence import EvidenceListResponse, EvidenceResponse

router = APIRouter(tags=["evidence"])


@router.get(
    "/projects/{project_id}/evidence",
    response_model=EvidenceListResponse,
    summary="List durable research evidence for a project",
    operation_id="listProjectEvidence",
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Project not found."},
    },
)
def list_project_evidence(
    project_id: str,
    evidence_service: EvidenceServiceDep,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
    workflow_run_id: str | None = Query(default=None),
    research_question_id: str | None = Query(default=None),
    information_need_id: str | None = Query(default=None),
    source_id: str | None = Query(default=None),
) -> EvidenceListResponse:
    authorization.require_project(principal, project_id)
    evidence_items = evidence_service.list_evidence_for_project(
        project_id,
        workflow_run_id=workflow_run_id,
        research_question_id=research_question_id,
        information_need_id=information_need_id,
        source_id=source_id,
    )
    return EvidenceListResponse(
        items=[evidence_to_response(item) for item in evidence_items],
        count=len(evidence_items),
    )


@router.get(
    "/evidence/{evidence_id}",
    response_model=EvidenceResponse,
    summary="Get durable research evidence by id",
    operation_id="getEvidence",
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Evidence not found."},
    },
)
def get_evidence(
    evidence_id: str,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
) -> EvidenceResponse:
    evidence, _ = authorization.require_evidence(principal, evidence_id)
    return evidence_to_response(evidence)

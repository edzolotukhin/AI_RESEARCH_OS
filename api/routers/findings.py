from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.auth import AuthorizationDep, PrincipalDep, bearer_scheme
from api.dependencies import FindingServiceDep, InsightServiceDep
from api.mappers.finding_mappers import finding_to_response, insight_to_response
from api.schemas.findings import FindingListResponse, FindingResponse, InsightListResponse, InsightResponse

router = APIRouter(tags=["findings"])


@router.get(
    "/projects/{project_id}/findings",
    response_model=FindingListResponse,
    summary="List durable research findings for a project",
    operation_id="listProjectFindings",
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Project not found."},
    },
)
def list_project_findings(
    project_id: str,
    finding_service: FindingServiceDep,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
    workflow_run_id: str | None = Query(default=None),
    research_question_id: str | None = Query(default=None),
    information_need_id: str | None = Query(default=None),
    evidence_id: str | None = Query(default=None),
) -> FindingListResponse:
    authorization.require_project(principal, project_id)
    findings = finding_service.list_findings_for_project(
        project_id,
        workflow_run_id=workflow_run_id,
        research_question_id=research_question_id,
        information_need_id=information_need_id,
        evidence_id=evidence_id,
    )
    return FindingListResponse(
        items=[finding_to_response(item) for item in findings],
        count=len(findings),
    )


@router.get(
    "/findings/{finding_id}",
    response_model=FindingResponse,
    summary="Get durable research finding by id",
    operation_id="getFinding",
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Finding not found."},
    },
)
def get_finding(
    finding_id: str,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
) -> FindingResponse:
    finding, _ = authorization.require_finding(principal, finding_id)
    return finding_to_response(finding)


@router.get(
    "/projects/{project_id}/insights",
    response_model=InsightListResponse,
    summary="List durable research insights for a project",
    operation_id="listProjectInsights",
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Project not found."},
    },
)
def list_project_insights(
    project_id: str,
    insight_service: InsightServiceDep,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
    workflow_run_id: str | None = Query(default=None),
    research_question_id: str | None = Query(default=None),
    finding_id: str | None = Query(default=None),
) -> InsightListResponse:
    authorization.require_project(principal, project_id)
    insights = insight_service.list_insights_for_project(
        project_id,
        workflow_run_id=workflow_run_id,
        research_question_id=research_question_id,
        finding_id=finding_id,
    )
    return InsightListResponse(
        items=[insight_to_response(item) for item in insights],
        count=len(insights),
    )


@router.get(
    "/insights/{insight_id}",
    response_model=InsightResponse,
    summary="Get durable research insight by id",
    operation_id="getInsight",
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Insight not found."},
    },
)
def get_insight(
    insight_id: str,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
) -> InsightResponse:
    insight, _ = authorization.require_insight(principal, insight_id)
    return insight_to_response(insight)

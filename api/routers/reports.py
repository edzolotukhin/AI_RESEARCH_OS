from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.auth import AuthorizationDep, PrincipalDep, bearer_scheme
from api.dependencies import ReportQueryServiceDep, ContainerDep
from api.mappers.report_mappers import report_to_response
from api.schemas.reports import ReportListResponse, ReportResponse

router = APIRouter(tags=["reports"])


@router.get(
    "/projects/{project_id}/reports",
    response_model=ReportListResponse,
    summary="List durable research reports for a project",
    operation_id="listProjectReports",
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Project not found."},
    },
)
def list_project_reports(
    project_id: str,
    report_service: ReportQueryServiceDep,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
    container: ContainerDep,
    workflow_run_id: str | None = Query(default=None),
) -> ReportListResponse:
    authorization.require_project(principal, project_id)
    reports = report_service.list_reports_for_project(
        project_id,
        workflow_run_id=workflow_run_id,
    )
    return ReportListResponse(
        items=[report_to_response(item, delivery=_editorial_delivery(container, item)) for item in reports],
        count=len(reports),
    )


@router.get(
    "/reports/{report_id}",
    response_model=ReportResponse,
    summary="Get durable research report by id",
    operation_id="getReport",
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Report not found."},
    },
)
def get_report(
    report_id: str,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
    container: ContainerDep,
) -> ReportResponse:
    report, _ = authorization.require_report(principal, report_id)
    return report_to_response(report, delivery=_editorial_delivery(container, report))


def _editorial_delivery(container, report):
    from application.report.editorial_contract import EDITORIAL_CONTRACT_VERSION
    if report.metadata.get("report_contract_version") != EDITORIAL_CONTRACT_VERSION:
        return None
    reviews = container.review_query_service.list_reviews_for_project(
        report.project_id, workflow_run_id=report.workflow_run_id, report_id=report.id,
    )
    if len(reviews) != 1:
        return None
    try:
        from application.deliverables.editorial_delivery import load_approved_editorial_delivery
        repository = container.project_deliverables_service.report_claims
        claims = tuple(repository.list_for_report(report.id, report.revision_number))
        return load_approved_editorial_delivery(report=report, review=reviews[0], claims=claims)
    except (AttributeError, ValueError):
        return None

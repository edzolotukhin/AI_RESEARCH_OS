"""Thin public Research API facade (P1-19.1).

Maps external Research contracts onto existing Project/WorkflowRun submission
and P1-18.1 ResearchRunResult projection. No parallel write model.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Response, status
from fastapi.responses import JSONResponse

from api.auth import AuthorizationDep, PrincipalDep, bearer_scheme
from api.dependencies import (
    AgencyDep,
    ContainerDep,
    ResearchRunResultQueryServiceDep,
    ResearchStatusQueryServiceDep,
)
from api.routers.workflow_runs import start_research
from api.schemas.common import ErrorDetail, ErrorResponse
from api.schemas.research import (
    ResearchResultDetailResponse,
    ResearchResultResponse,
    ResearchStatusResponse,
    ResearchSubmissionResponse,
    SubmitResearchRequest,
)
from api.schemas.workflow_runs import StartResearchRequest
from application.persistence.exceptions import (
    AccessDeniedError,
    EntityNotFoundError,
)
from application.query.research_run_result import ResearchRunResultProjectionError
from application.query.research_status import ResearchExecutionStatus
from application.runtime.background_execution_capability import (
    requires_http_background_submission,
)

router = APIRouter(prefix="/research", tags=["research"])
logger = logging.getLogger(__name__)


def _error(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            details=details or {},
        ),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


def _project_name_from_brief(title: str) -> str:
    cleaned = (title or "").strip()
    if not cleaned:
        return "Research"
    return cleaned[:200]


@router.post(
    "",
    response_model=ResearchSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit Research from a public Brief",
    operation_id="submitResearch",
    description=(
        "User-facing Research submit. Creates a Project when project_id is omitted, "
        "then reuses the existing Research submission/planning path. Returns "
        "research_id (alias of workflow run id) and projected execution status. "
        "Poll GET /research/{research_id} then GET /research/{research_id}/result."
    ),
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Project not found."},
        409: {"description": "Background execution or idempotency conflict."},
        422: {"description": "Invalid Research Brief."},
    },
)
def submit_research(
    body: SubmitResearchRequest,
    agency: AgencyDep,
    container: ContainerDep,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
    response: Response,
    status_query: ResearchStatusQueryServiceDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
) -> ResearchSubmissionResponse:
    if container.background_execution is not None:
        requires_http_background_submission(container.background_execution)

    if body.project_id:
        project = authorization.require_project(principal, body.project_id)
        project_id = project.id
    else:
        project = agency.create_project(
            _project_name_from_brief(body.brief.title),
            owner_principal_id=principal.principal_id,
        )
        project_id = project.id

    start_body = StartResearchRequest(
        brief=body.brief,
        correlation_id=body.correlation_id,
        source=body.source,
    )
    # Reuse the accepted production submission path (planning + run create).
    start_payload = start_research(
        project_id=project_id,
        body=start_body,
        agency=agency,
        container=container,
        authorization=authorization,
        principal=principal,
        response=response,
        idempotency_key=idempotency_key,
        x_correlation_id=x_correlation_id,
    )
    research_id = start_payload.run_id
    response.headers["Location"] = f"/research/{research_id}"
    status_projection = status_query.get_status(research_id)
    payload = status_projection.to_dict()
    # Fresh submit does not fabricate a product outcome.
    if status_projection.execution_status != ResearchExecutionStatus.TERMINAL:
        payload["product_outcome"] = None
        payload["result_available"] = False
    logger.info(
        "public_research_submitted",
        extra={
            "request_id": str(uuid4()),
            "correlation_id": body.correlation_id or x_correlation_id,
            "route": "submitResearch",
            "status": 202,
            "research_id": research_id,
            "project_id": project_id,
            "principal_id": principal.principal_id,
        },
    )
    return ResearchSubmissionResponse.model_validate(payload)


@router.get(
    "/{research_id}",
    response_model=ResearchStatusResponse,
    summary="Get projected Research status",
    operation_id="getResearchStatus",
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Research not found."},
    },
)
def get_research_status(
    research_id: str,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
    status_query: ResearchStatusQueryServiceDep,
) -> ResearchStatusResponse | JSONResponse:
    try:
        authorization.require_run(principal, research_id)
        projection = status_query.get_status(research_id)
    except (AccessDeniedError, EntityNotFoundError):
        return _error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="research_not_found",
            message="Research not found.",
            details={"research_id": research_id},
        )
    return ResearchStatusResponse.model_validate(projection.to_dict())


@router.get(
    "/{research_id}/result",
    response_model=ResearchResultResponse,
    summary="Get coherent terminal Research result",
    operation_id="getResearchResult",
    description=(
        "Returns the P1-18.1 ResearchRunResult projection. Available only for "
        "terminal Research. Product outcomes including NOT_READY return HTTP 200."
    ),
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Research not found."},
        409: {"description": "Research is still running."},
    },
)
def get_research_result(
    research_id: str,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
    result_query: ResearchRunResultQueryServiceDep,
) -> ResearchResultResponse | JSONResponse:
    try:
        workflow_run, _ = authorization.require_run(principal, research_id)
    except (AccessDeniedError, EntityNotFoundError):
        return _error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="research_not_found",
            message="Research not found.",
            details={"research_id": research_id},
        )

    from application.query.research_status_query_service import (
        ResearchStatusQueryService,
    )

    execution_status = ResearchStatusQueryService.project_execution_status(
        workflow_run,
    )
    phase = ResearchStatusQueryService.project_phase(workflow_run)
    if execution_status != ResearchExecutionStatus.TERMINAL:
        return _error(
            status_code=status.HTTP_409_CONFLICT,
            code="research_not_terminal",
            message="Research is still running.",
            details={
                "research_id": research_id,
                "execution_status": execution_status.value,
                "phase": phase.value,
            },
        )

    try:
        result = result_query.get_for_run(research_id)
    except EntityNotFoundError:
        return _error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="research_not_found",
            message="Research not found.",
            details={"research_id": research_id},
        )
    except ResearchRunResultProjectionError as exc:
        message = str(exc)
        if "not terminal" in message.lower():
            return _error(
                status_code=status.HTTP_409_CONFLICT,
                code="research_not_terminal",
                message="Research is still running.",
                details={
                    "research_id": research_id,
                    "execution_status": execution_status.value,
                    "phase": phase.value,
                },
            )
        return _error(
            status_code=status.HTTP_409_CONFLICT,
            code="research_result_unavailable",
            message="Research result cannot be projected safely.",
            details={"research_id": research_id},
        )

    return ResearchResultResponse.from_result_dict(result.to_dict())


@router.get(
    "/{research_id}/result/detail",
    response_model=ResearchResultDetailResponse,
    summary="Get inspectable terminal Research result detail",
    operation_id="getResearchResultDetail",
    description=(
        "Returns the P1-18.1 ResearchRunResult summary plus bounded inspectable "
        "entity detail for P1-20 UI consumption. Available only for terminal Research."
    ),
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Research not found."},
        409: {"description": "Research is still running."},
    },
)
def get_research_result_detail(
    research_id: str,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
    result_query: ResearchRunResultQueryServiceDep,
) -> ResearchResultDetailResponse | JSONResponse:
    try:
        workflow_run, _ = authorization.require_run(principal, research_id)
    except (AccessDeniedError, EntityNotFoundError):
        return _error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="research_not_found",
            message="Research not found.",
            details={"research_id": research_id},
        )

    from application.query.research_status_query_service import (
        ResearchStatusQueryService,
    )

    execution_status = ResearchStatusQueryService.project_execution_status(
        workflow_run,
    )
    phase = ResearchStatusQueryService.project_phase(workflow_run)
    if execution_status != ResearchExecutionStatus.TERMINAL:
        return _error(
            status_code=status.HTTP_409_CONFLICT,
            code="research_not_terminal",
            message="Research is still running.",
            details={
                "research_id": research_id,
                "execution_status": execution_status.value,
                "phase": phase.value,
            },
        )

    try:
        result = result_query.get_detail_for_run(research_id)
    except EntityNotFoundError:
        return _error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="research_not_found",
            message="Research not found.",
            details={"research_id": research_id},
        )
    except ResearchRunResultProjectionError as exc:
        message = str(exc)
        if "not terminal" in message.lower():
            return _error(
                status_code=status.HTTP_409_CONFLICT,
                code="research_not_terminal",
                message="Research is still running.",
                details={
                    "research_id": research_id,
                    "execution_status": execution_status.value,
                    "phase": phase.value,
                },
            )
        return _error(
            status_code=status.HTTP_409_CONFLICT,
            code="research_result_unavailable",
            message="Research result cannot be projected safely.",
            details={"research_id": research_id},
        )

    return ResearchResultDetailResponse.from_detail_dict(result.to_dict())

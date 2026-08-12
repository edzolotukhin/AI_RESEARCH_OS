"""In-process Research facade for the server-rendered UI (P1-20.1).

Calls the same application services as the public P1-19 Research API without
HTTP self-calls or workflow/task/repository endpoints.
"""

from __future__ import annotations

from typing import Any

from fastapi import Response

from api.routers.workflow_runs import start_research
from api.schemas.workflow_runs import ResearchBriefRequest, StartResearchRequest
from application.container import ApplicationContainer
from application.persistence.exceptions import (
    AccessDeniedError,
    EntityNotFoundError,
)
from application.query.research_run_result import ResearchRunResultProjectionError
from application.query.research_status import ResearchExecutionStatus
from application.runtime.background_execution_capability import (
    requires_http_background_submission,
)
from application.security.principal import AuthenticatedPrincipal
from application.services.authorization_service import AuthorizationService
from domain.research_brief import ResearchBrief


class ResearchUiFacade:
    """Narrow UI client over the public Research application layer."""

    def __init__(
        self,
        *,
        container: ApplicationContainer,
        principal: AuthenticatedPrincipal,
        authorization: AuthorizationService,
    ) -> None:
        self._container = container
        self._principal = principal
        self._authorization = authorization

    def submit_research(
        self,
        *,
        brief_payload: dict[str, Any],
        response: Response,
    ) -> dict[str, Any]:
        if self._container.background_execution is not None:
            requires_http_background_submission(self._container.background_execution)

        brief = ResearchBrief.from_dict(brief_payload)
        if not (brief.business_question or "").strip():
            raise ValueError("business_question is required")

        project = self._container.agency.create_project(
            self._project_name_from_brief(brief.title),
            owner_principal_id=self._principal.principal_id,
        )
        start_body = StartResearchRequest(
            brief=ResearchBriefRequest.model_validate(brief.to_dict()),
        )
        start_payload = start_research(
            project_id=project.id,
            body=start_body,
            agency=self._container.agency,
            container=self._container,
            authorization=self._authorization,
            principal=self._principal,
            response=response,
            idempotency_key=None,
            x_correlation_id=None,
        )
        research_id = start_payload.run_id
        status_projection = self._container.research_status_query_service.get_status(
            research_id,
        )
        payload = status_projection.to_dict()
        if status_projection.execution_status != ResearchExecutionStatus.TERMINAL:
            payload["product_outcome"] = None
            payload["result_available"] = False
        return payload

    def get_status(self, research_id: str) -> dict[str, Any]:
        self._authorization.require_run(self._principal, research_id)
        return self._container.research_status_query_service.get_status(
            research_id,
        ).to_dict()

    def get_result_detail(self, research_id: str) -> dict[str, Any]:
        workflow_run, _ = self._authorization.require_run(
            self._principal,
            research_id,
        )
        from application.query.research_status_query_service import (
            ResearchStatusQueryService,
        )

        execution_status = ResearchStatusQueryService.project_execution_status(
            workflow_run,
        )
        if execution_status != ResearchExecutionStatus.TERMINAL:
            raise ResearchRunResultProjectionError(
                f"WorkflowRun is not terminal: {research_id}",
            )
        detail = self._container.research_run_result_query_service.get_detail_for_run(
            research_id,
        )
        return detail.to_dict()

    @staticmethod
    def _project_name_from_brief(title: str) -> str:
        cleaned = (title or "").strip()
        if not cleaned:
            return "Research"
        return cleaned[:200]


def build_research_ui_facade(container: ApplicationContainer) -> ResearchUiFacade:
    from api.ui.principal import resolve_ui_principal

    principal = resolve_ui_principal(container)
    if container.authorization_service is None:
        raise RuntimeError("Authorization is not configured for this deployment.")
    return ResearchUiFacade(
        container=container,
        principal=principal,
        authorization=container.authorization_service,
    )

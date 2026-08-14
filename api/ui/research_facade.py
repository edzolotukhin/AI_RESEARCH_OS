"""In-process Research facade for the server-rendered UI (P1-20.1).

Calls the same application services as the public P1-19 Research API without
HTTP self-calls or workflow/task/repository endpoints.
"""

from __future__ import annotations

from typing import Any

from fastapi import Response

from application.container import ApplicationContainer
from application.persistence.exceptions import (
    AccessDeniedError,
    DuplicateEntityError,
    EntityNotFoundError,
)
from application.persistence.records import ResearchSubmissionStatus
from application.query.research_run_result import ResearchRunResultProjectionError
from application.query.research_status import ResearchExecutionStatus
from application.runtime.background_execution_capability import (
    requires_http_background_submission,
)
from application.runtime.logical_submission_identity import (
    normalize_submission_key,
    project_id_for_submission,
)
from application.runtime.research_request_fingerprint import (
    compute_research_request_fingerprint,
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
        submission_key: str,
    ) -> dict[str, Any]:
        if self._container.background_execution is not None:
            requires_http_background_submission(self._container.background_execution)

        brief = ResearchBrief.from_dict(brief_payload)
        if not (brief.business_question or "").strip():
            raise ValueError("business_question is required")

        key = normalize_submission_key(submission_key)
        project_id = project_id_for_submission(
            principal_id=self._principal.principal_id,
            submission_key=key,
        )
        try:
            project = self._container.agency.create_project(
                self._project_name_from_brief(brief.title),
                owner_principal_id=self._principal.principal_id,
                project_id=project_id,
            )
        except DuplicateEntityError:
            project = self._authorization.require_project(
                self._principal,
                project_id,
            )

        submission_service = self._container.research_submission_service
        if submission_service is None or not submission_service.enabled:
            raise RuntimeError("Durable Research submission registry is unavailable.")
        fingerprint = compute_research_request_fingerprint(
            project_id=project_id,
            brief=brief.to_fingerprint_dict(),
        )
        reservation = submission_service.resolve_submission(
            project_id=project_id,
            idempotency_key=key,
            request_fingerprint=fingerprint,
            correlation_id=None,
            source="ui",
        )
        if not reservation.created:
            return self.get_submission_status(key)

        project.research_brief = brief
        try:
            context = self._container.agency.start_research(
                project,
                run_id=reservation.run_id,
            )
        except Exception:
            submission_service.mark_failed(
                project_id=project_id,
                idempotency_key=key,
            )
            raise
        submission_service.mark_completed(
            project_id=project_id,
            idempotency_key=key,
        )
        research_id = context.workflow_run.id
        status_projection = self._container.research_status_query_service.get_status(
            research_id,
        )
        payload = status_projection.to_dict()
        payload.update(
            {
                "submission_key": key,
                "submission_status": ResearchSubmissionStatus.COMPLETED,
                "project_id": project_id,
                "research_id": research_id,
                "run_id": research_id,
            }
        )
        if status_projection.execution_status != ResearchExecutionStatus.TERMINAL:
            payload["product_outcome"] = None
            payload["result_available"] = False
        return payload

    def get_submission_status(self, submission_key: str) -> dict[str, Any]:
        key = normalize_submission_key(submission_key)
        project_id = project_id_for_submission(
            principal_id=self._principal.principal_id,
            submission_key=key,
        )
        self._authorization.require_project(self._principal, project_id)
        submission_service = self._container.research_submission_service
        if submission_service is None or not submission_service.enabled:
            raise RuntimeError("Durable Research submission registry is unavailable.")
        record = submission_service.get_submission(
            project_id=project_id,
            idempotency_key=key,
        )
        if record is None:
            raise EntityNotFoundError(f"Research submission not found: {key}")

        payload: dict[str, Any] = {
            "submission_key": key,
            "submission_status": record.status,
            "project_id": project_id,
            "research_id": None,
            "run_id": None,
            "execution_status": "SUBMITTING",
            "research_url": None,
        }
        try:
            workflow_run, _ = self._authorization.require_run(
                self._principal,
                record.run_id,
            )
        except EntityNotFoundError:
            if record.status == ResearchSubmissionStatus.FAILED:
                payload["execution_status"] = "SUBMISSION_FAILED"
            return payload

        payload.update(
            self._container.research_status_query_service.get_status(
                workflow_run.id,
            ).to_dict()
        )
        payload.update(
            {
                "research_id": workflow_run.id,
                "run_id": workflow_run.id,
                "research_url": f"/ui/research/{workflow_run.id}",
            }
        )
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

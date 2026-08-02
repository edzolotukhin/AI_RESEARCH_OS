from __future__ import annotations

from application.persistence.exceptions import AccessDeniedError, EntityNotFoundError
from application.security.principal import AuthenticatedPrincipal
from application.services.artifact_service import ArtifactService
from application.services.project_service import ProjectService
from application.services.workflow_service import WorkflowService
from application.services.evidence_service import EvidenceService
from application.services.source_service import SourceService
from domain.evidence.evidence import Evidence
from domain.project import Project
from domain.sources.source import Source
from domain.workflow_run import WorkflowRun


class AuthorizationService:
    """Enforces principal-scoped access to projects and derived resources."""

    def __init__(
        self,
        *,
        project_service: ProjectService,
        workflow_service: WorkflowService,
        artifact_service: ArtifactService | None = None,
        source_service: SourceService | None = None,
        evidence_service: EvidenceService | None = None,
    ) -> None:
        self._project_service = project_service
        self._workflow_service = workflow_service
        self._artifact_service = artifact_service
        self._source_service = source_service
        self._evidence_service = evidence_service

    def require_project(
        self,
        principal: AuthenticatedPrincipal,
        project_id: str,
    ) -> Project:
        try:
            project = self._project_service.get_project(project_id)
        except EntityNotFoundError as exc:
            raise AccessDeniedError(str(exc)) from exc

        if project.owner_principal_id != principal.principal_id:
            raise AccessDeniedError(f"Project not found: {project_id}")
        return project

    def require_run(
        self,
        principal: AuthenticatedPrincipal,
        run_id: str,
    ) -> tuple[WorkflowRun, Project]:
        try:
            workflow_run = self._workflow_service.get_workflow_run(run_id)
        except EntityNotFoundError as exc:
            raise AccessDeniedError(str(exc)) from exc

        project = self.require_project(principal, workflow_run.project_id)
        return workflow_run, project

    def require_source(
        self,
        principal: AuthenticatedPrincipal,
        source_id: str,
    ) -> tuple[Source, Project]:
        if self._source_service is None:
            raise AccessDeniedError(f"Source not found: {source_id}")
        try:
            source = self._source_service.get_source(source_id)
        except EntityNotFoundError as exc:
            raise AccessDeniedError(str(exc)) from exc
        project = self.require_project(principal, source.project_id)
        return source, project

    def require_evidence(
        self,
        principal: AuthenticatedPrincipal,
        evidence_id: str,
    ) -> tuple[Evidence, Project]:
        if self._evidence_service is None:
            raise AccessDeniedError(f"Evidence not found: {evidence_id}")
        try:
            evidence = self._evidence_service.get_evidence(evidence_id)
        except EntityNotFoundError as exc:
            raise AccessDeniedError(str(exc)) from exc
        project = self.require_project(principal, evidence.project_id)
        return evidence, project

    def list_visible_projects(
        self,
        principal: AuthenticatedPrincipal,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[Project]:
        return self._project_service.list_projects(
            owner_principal_id=principal.principal_id,
            offset=offset,
            limit=limit,
        )

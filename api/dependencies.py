from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from agency.agency import Agency
from application.container import ApplicationContainer
from application.services.artifact_service import ArtifactService
from application.services.execution_log_service import ExecutionLogService
from application.services.project_service import ProjectService
from application.services.evidence_service import EvidenceService
from application.services.finding_service import FindingService, InsightService
from application.services.report_query_service import ReportQueryService
from application.services.review_query_service import ReviewQueryService
from application.services.source_service import SourceService
from application.services.workflow_service import WorkflowService
from application.query.research_run_result_query_service import (
    ResearchRunResultQueryService,
)
from application.query.research_status_query_service import (
    ResearchStatusQueryService,
)


def get_container(request: Request) -> ApplicationContainer:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise RuntimeError("Application container is not configured.")
    return container


ContainerDep = Annotated[ApplicationContainer, Depends(get_container)]


def get_agency(container: ContainerDep) -> Agency:
    return container.agency


def get_project_service(container: ContainerDep) -> ProjectService:
    return container.project_service


def get_workflow_service(container: ContainerDep) -> WorkflowService:
    return container.workflow_service


def get_artifact_service(container: ContainerDep) -> ArtifactService:
    return container.artifact_service


def get_execution_log_service(container: ContainerDep) -> ExecutionLogService:
    return container.execution_log_service


def get_source_service(container: ContainerDep) -> SourceService:
    return container.source_service


def get_evidence_service(container: ContainerDep) -> EvidenceService:
    return container.evidence_service


def get_finding_service(container: ContainerDep) -> FindingService:
    return container.finding_service


def get_insight_service(container: ContainerDep) -> InsightService:
    return container.insight_service


def get_report_query_service(container: ContainerDep) -> ReportQueryService:
    return container.report_query_service


def get_review_query_service(container: ContainerDep) -> ReviewQueryService:
    return container.review_query_service


def get_research_run_result_query_service(
    container: ContainerDep,
) -> ResearchRunResultQueryService:
    return container.research_run_result_query_service


def get_research_status_query_service(
    container: ContainerDep,
) -> ResearchStatusQueryService:
    return container.research_status_query_service


AgencyDep = Annotated[Agency, Depends(get_agency)]
ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]
WorkflowServiceDep = Annotated[WorkflowService, Depends(get_workflow_service)]
ArtifactServiceDep = Annotated[ArtifactService, Depends(get_artifact_service)]
SourceServiceDep = Annotated[SourceService, Depends(get_source_service)]
EvidenceServiceDep = Annotated[EvidenceService, Depends(get_evidence_service)]
FindingServiceDep = Annotated[FindingService, Depends(get_finding_service)]
InsightServiceDep = Annotated[InsightService, Depends(get_insight_service)]
ReportQueryServiceDep = Annotated[ReportQueryService, Depends(get_report_query_service)]
ReviewQueryServiceDep = Annotated[ReviewQueryService, Depends(get_review_query_service)]
ResearchRunResultQueryServiceDep = Annotated[
    ResearchRunResultQueryService,
    Depends(get_research_run_result_query_service),
]
ResearchStatusQueryServiceDep = Annotated[
    ResearchStatusQueryService,
    Depends(get_research_status_query_service),
]
ExecutionLogServiceDep = Annotated[
    ExecutionLogService,
    Depends(get_execution_log_service),
]

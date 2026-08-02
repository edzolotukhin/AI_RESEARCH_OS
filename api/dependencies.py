from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from agency.agency import Agency
from application.container import ApplicationContainer
from application.services.artifact_service import ArtifactService
from application.services.execution_log_service import ExecutionLogService
from application.services.project_service import ProjectService
from application.services.source_service import SourceService
from application.services.workflow_service import WorkflowService


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


AgencyDep = Annotated[Agency, Depends(get_agency)]
ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]
WorkflowServiceDep = Annotated[WorkflowService, Depends(get_workflow_service)]
ArtifactServiceDep = Annotated[ArtifactService, Depends(get_artifact_service)]
SourceServiceDep = Annotated[SourceService, Depends(get_source_service)]
ExecutionLogServiceDep = Annotated[
    ExecutionLogService,
    Depends(get_execution_log_service),
]

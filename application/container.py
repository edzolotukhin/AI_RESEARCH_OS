from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from agency.agency import Agency
from application.config import ApplicationConfig
from application.services.artifact_service import ArtifactService
from application.services.execution_log_service import ExecutionLogService
from application.services.knowledge_service import KnowledgeService
from application.services.project_service import ProjectService
from application.services.durable_workflow_service import DurableWorkflowService
from application.services.workflow_service import WorkflowService
from application.services.research_submission_service import ResearchSubmissionService
from application.services.worker_execution_service import WorkerExecutionService

from application.runtime.background_execution_capability import (
    BackgroundExecutionCapability,
)


ReadinessCheck = Callable[[], tuple[bool, str]]
ShutdownCallback = Callable[[], None]


@dataclass
class ApplicationContainer:
    """Composition result exposing application services for entry points."""

    config: ApplicationConfig
    agency: Agency
    project_service: ProjectService
    workflow_service: WorkflowService
    artifact_service: ArtifactService
    knowledge_service: KnowledgeService
    execution_log_service: ExecutionLogService
    durable_workflow_service: DurableWorkflowService | None = None
    worker_execution_service: WorkerExecutionService | None = None
    research_submission_service: ResearchSubmissionService | None = None
    background_execution: BackgroundExecutionCapability | None = None
    readiness_check: ReadinessCheck | None = None
    _shutdown_callbacks: list[ShutdownCallback] = field(default_factory=list)

    @property
    def http_background_submission_supported(self) -> bool:
        return (
            self.background_execution is not None
            and self.background_execution.http_submission
        )

    def check_readiness(self) -> tuple[bool, str]:
        if self.readiness_check is not None:
            return self.readiness_check()
        return True, "ready"

    def shutdown(self) -> None:
        self.agency.shutdown()
        for callback in self._shutdown_callbacks:
            callback()

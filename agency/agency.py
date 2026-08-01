from __future__ import annotations

from typing import TYPE_CHECKING

from agents.planner.planner_agent import PlannerAgent
from application.services.project_service import ProjectService
from application.workflow_engine import WorkflowEngine
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.workflow_run import WorkflowRun
from loaders.agent_loader import AgentLoader
from runtime.workflow_context import WorkflowContext

if TYPE_CHECKING:
    from application.services.durable_workflow_service import DurableWorkflowService
    from domain.project import Project


class Agency:
    """
    Application facade for AI Research OS.

    Persistence use cases delegate to application services, not repositories.
    """

    def __init__(
        self,
        *,
        agent_loader: AgentLoader,
        project_service: ProjectService,
        planner_agent: PlannerAgent,
        workflow_run_factory: WorkflowRunFactory,
        workflow_engine: WorkflowEngine,
        durable_workflow_service: DurableWorkflowService | None = None,
        background_execution_enabled: bool = False,
    ) -> None:
        self._agent_loader = agent_loader
        self._project_service = project_service
        self._planner_agent = planner_agent
        self._workflow_run_factory = workflow_run_factory
        self._workflow_engine = workflow_engine
        self._durable_workflow_service = durable_workflow_service
        self._background_execution_enabled = background_execution_enabled

        self.initialized = False

    @property
    def durable_execution_available(self) -> bool:
        return self._durable_workflow_service is not None

    def initialize(self) -> None:
        self._agent_loader.load()
        self.initialized = True

    def shutdown(self) -> None:
        self.initialized = False

    def create_project(self, name: str) -> Project:
        return self._project_service.create_project(name)

    def get_project(self, project_id: str) -> Project:
        return self._project_service.get_project(project_id)

    def list_projects(
        self,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[Project]:
        return self._project_service.list_projects(offset=offset, limit=limit)

    def start_research(self, project: Project) -> WorkflowContext:
        if not self.initialized:
            self.initialize()

        planning_context = WorkflowContext(
            workflow_run=WorkflowRun(id="planning"),
            project=project,
        )

        planning_context = self._planner_agent.run(planning_context)

        workflow_template = planning_context.workflow_template

        if workflow_template is None:
            raise ValueError("Planner did not produce a WorkflowTemplate.")

        if planning_context.project is not None:
            project = planning_context.project

        if self._durable_workflow_service is not None:
            if self._background_execution_enabled:
                self._project_service.save_project(project, expected_version=0)
                return self._durable_workflow_service.submit_research(
                    project,
                    workflow_template,
                )
            return self._durable_workflow_service.start_research(
                project,
                workflow_template,
            )

        workflow_run = self._workflow_run_factory.create(
            template=workflow_template,
        )

        return self._workflow_engine.execute(
            project=project,
            workflow_template=workflow_template,
            workflow_run=workflow_run,
        )

    def submit_resume(self, run_id: str) -> WorkflowContext:
        if self._durable_workflow_service is None:
            raise RuntimeError(
                "Durable workflow execution is not enabled for the current "
                "persistence backend."
            )

        return self._durable_workflow_service.submit_resume(run_id)

    def resume_research(self, run_id: str) -> WorkflowContext:
        if self._durable_workflow_service is None:
            raise RuntimeError(
                "Durable workflow execution is not enabled for the current "
                "persistence backend."
            )

        if self._background_execution_enabled:
            return self._durable_workflow_service.submit_resume(run_id)

        return self._durable_workflow_service.resume_research(run_id)

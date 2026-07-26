from registry.registry import Registry

from loaders.agent_loader import AgentLoader

from infrastructure.project_repository import ProjectRepository

from domain.factories.project_factory import ProjectFactory
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory

from domain.task_definition import TaskDefinition

from runtime.research_context import ResearchContext

from application.executor_resolver import ExecutorResolver
from application.task_executor import TaskExecutor
from application.task_lifecycle_manager import TaskLifecycleManager
from application.task_scheduler import TaskScheduler
from application.workflow_engine import WorkflowEngine


class Agency:
    """
    Центральный объект AI Research OS.
    Composition Root + Application Facade.
    """

    def __init__(self):

        self.initialized = False

        # Registry
        self.registry = Registry()

        # Loaders
        self.agent_loader = AgentLoader(self.registry)

        # Factories
        self.project_factory = ProjectFactory()
        self.task_factory = TaskFactory()
        self.workflow_run_factory = WorkflowRunFactory(
            task_factory=self.task_factory,
        )

        # Repositories
        self.project_repository = ProjectRepository()

        # Runtime
        self.executor_resolver = ExecutorResolver(self.registry)

        self.task_lifecycle_manager = TaskLifecycleManager()

        self.task_scheduler = TaskScheduler()

        self.task_executor = TaskExecutor(
            resolver=self.executor_resolver,
            lifecycle=self.task_lifecycle_manager,
        )

        self.workflow_engine = WorkflowEngine(
            scheduler=self.task_scheduler,
            task_executor=self.task_executor,
        )

    def initialize(self):

        self.agent_loader.load()

        self.initialized = True

    def shutdown(self):

        self.initialized = False

    def create_project(
        self,
        name: str,
    ):

        project = self.project_factory.create(name)

        self.project_repository.create_project(project)
        self.project_repository.save_project(project)

        return project

    def start_research(
        self,
        project,
    ) -> ResearchContext:

        context = ResearchContext(
            project=project,
        )

        planner_definition = TaskDefinition(
            id="build_research_plan",
            name="Build Research Plan",
            executor_id="planner",
        )

        planner_task = self.task_factory.create(
            planner_definition,
        )

        context = self.task_executor.execute(
            task=planner_task,
            context=context,
        )

        context.workflow_run = self.workflow_run_factory.create(
            template=context.workflow_template,
            run_id="run-001",
        )

        context = self.workflow_engine.execute(
            context,
        )

        return context
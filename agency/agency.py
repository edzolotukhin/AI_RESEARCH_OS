from agents.planner.planner_agent import PlannerAgent



from application.workflow_engine import WorkflowEngine



from domain.factories.project_factory import ProjectFactory

from domain.factories.workflow_run_factory import WorkflowRunFactory

from domain.workflow_run import WorkflowRun



from infrastructure.project_repository import ProjectRepository



from loaders.agent_loader import AgentLoader



from runtime.workflow_context import WorkflowContext





class Agency:

    """

    Application facade for AI Research OS.

    """



    def __init__(

        self,

        *,

        agent_loader: AgentLoader,

        project_factory: ProjectFactory,

        project_repository: ProjectRepository,

        planner_agent: PlannerAgent,

        workflow_run_factory: WorkflowRunFactory,

        workflow_engine: WorkflowEngine,

        workflow_run_id: str = "run-001",

    ) -> None:

        self._agent_loader = agent_loader

        self._project_factory = project_factory

        self._project_repository = project_repository

        self._planner_agent = planner_agent

        self._workflow_run_factory = workflow_run_factory

        self._workflow_engine = workflow_engine

        self._workflow_run_id = workflow_run_id



        self.initialized = False



    def initialize(self) -> None:

        self._agent_loader.load()

        self.initialized = True



    def shutdown(self) -> None:

        self.initialized = False



    def create_project(

        self,

        name: str,

    ):

        project = self._project_factory.create(name)



        self._project_repository.create_project(project)

        self._project_repository.save_project(project)



        return project



    def start_research(

        self,

        project,

    ) -> WorkflowContext:

        planning_context = WorkflowContext(

            workflow_run=WorkflowRun(id="planning"),

            project=project,

        )



        planning_context = self._planner_agent.run(

            planning_context,

        )



        workflow_template = planning_context.workflow_template



        if workflow_template is None:

            raise ValueError("Planner did not produce a WorkflowTemplate.")



        workflow_run = self._workflow_run_factory.create(

            template=workflow_template,

            run_id=self._workflow_run_id,

        )



        return self._workflow_engine.execute(

            project=project,

            workflow_template=workflow_template,

            workflow_run=workflow_run,

        )


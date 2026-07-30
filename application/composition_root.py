from __future__ import annotations

from application.config import ApplicationConfig, ApplicationOverrides
from application.executor_resolver import ExecutorResolver
from application.factories.research_plan_factory import ResearchPlanFactory
from application.parsers.planner_response_parser import PlannerResponseParser
from application.planner.service import PlannerServiceImpl
from application.planner.workflow_template_mapper import (
    ResearchPlanWorkflowTemplateMapper,
)
from application.prompts.builders.planner_prompt_builder import (
    PlannerPromptBuilder,
)
from application.prompts.file_template_loader import FileTemplateLoader
from application.prompts.python_format_prompt_renderer import (
    PythonFormatPromptRenderer,
)
from application.runtime.workflow_completion_policy import (
    WorkflowCompletionPolicy,
)
from application.task_executor import TaskExecutor
from application.task_lifecycle_manager import TaskLifecycleManager
from application.task_scheduler import TaskScheduler
from application.workflow_engine import WorkflowEngine

from agency.agency import Agency

from agents.analysis.analysis_agent import AnalysisAgent
from agents.planner.planner_agent_factory import PlannerAgentFactory
from agents.planner.planner_executor import PlannerExecutor
from agents.proposal.proposal_agent import ProposalAgent
from agents.report.report_agent import ReportAgent
from agents.search.search_agent import SearchAgent

from application.executors.agent_executor import AgentExecutor

from domain.factories.project_factory import ProjectFactory
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory

from application.planner.payload_contract import PlannerPayloadContract
from application.structured_output.parser import StructuredOutputParser
from infrastructure.project_repository import ProjectRepository

from loaders.agent_loader import AgentLoader

from registry.registry import Registry


def create_application(
    config: ApplicationConfig | None = None,
    overrides: ApplicationOverrides | None = None,
) -> Agency:
    """
    Composition Root for AI Research OS.

    Builds the application object graph and returns the Agency facade.
    """
    config = config or ApplicationConfig()
    overrides = overrides or ApplicationOverrides()

    registry = overrides.registry or Registry()

    project_repository = overrides.project_repository or ProjectRepository(
        projects_root=config.projects_root,
    )

    llm_client = overrides.llm_client or _create_llm_client(config)

    template_loader = FileTemplateLoader()
    prompt_renderer = PythonFormatPromptRenderer()
    planner_prompt_builder = PlannerPromptBuilder(
        template_loader=template_loader,
        prompt_renderer=prompt_renderer,
    )

    workflow_template_mapper = ResearchPlanWorkflowTemplateMapper()

    structured_output_parser = StructuredOutputParser()
    planner_payload_contract = PlannerPayloadContract(
        response_parser=PlannerResponseParser(),
    )

    planner_service = PlannerServiceImpl(
        response_parser=PlannerResponseParser(),
        plan_factory=ResearchPlanFactory(),
    )

    if overrides.planner_agent is not None:
        planner_agent = overrides.planner_agent
    else:
        planner_agent = PlannerAgentFactory(
            planner_service=planner_service,
            workflow_mapper=workflow_template_mapper,
            prompt_builder=planner_prompt_builder,
            llm_client=llm_client,
            structured_output_parser=structured_output_parser,
            payload_contract=planner_payload_contract,
        ).create()

    agent_loader = AgentLoader(
        registry=registry,
        executors={
            "planner": PlannerExecutor(agent=planner_agent),
            "search": AgentExecutor(agent=SearchAgent()),
            "analysis": AgentExecutor(agent=AnalysisAgent()),
            "report": AgentExecutor(agent=ReportAgent()),
            "proposal": AgentExecutor(agent=ProposalAgent()),
        },
    )

    project_factory = ProjectFactory()

    workflow_run_factory = WorkflowRunFactory(
        task_factory=TaskFactory(),
    )

    executor_resolver = ExecutorResolver(
        agent_registry=registry.agents,
        tool_registry=registry.tools,
        human_registry=registry.human_executors,
        api_registry=registry.api_executors,
    )

    task_lifecycle_manager = TaskLifecycleManager()
    task_scheduler = TaskScheduler()
    completion_policy = WorkflowCompletionPolicy()

    task_executor = TaskExecutor(
        resolver=executor_resolver,
        lifecycle=task_lifecycle_manager,
    )

    workflow_engine = WorkflowEngine(
        scheduler=task_scheduler,
        task_executor=task_executor,
        completion_policy=completion_policy,
    )

    return Agency(
        agent_loader=agent_loader,
        project_factory=project_factory,
        project_repository=project_repository,
        planner_agent=planner_agent,
        workflow_run_factory=workflow_run_factory,
        workflow_engine=workflow_engine,
        workflow_run_id=config.workflow_run_id,
    )


def _create_llm_client(config: ApplicationConfig):
    from infrastructure.llm.llm_configuration import LLMConfiguration
    from infrastructure.llm.openai_client import OpenAIClient

    llm_configuration = LLMConfiguration(
        model=config.llm_model,
        max_tokens=config.llm_max_tokens,
    )

    return OpenAIClient(configuration=llm_configuration)

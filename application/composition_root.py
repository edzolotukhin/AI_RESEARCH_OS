from __future__ import annotations

from application.config import ApplicationConfig, ApplicationOverrides
from application.executor_resolver import ExecutorResolver
from application.factories.research_plan_factory import ResearchPlanFactory
from application.parsers.planner_response_parser import PlannerResponseParser
from application.planner.executor_catalog import ExecutorCatalog
from application.planner.executor_definitions import AGENT_EXECUTOR_CAPABILITIES
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

from application.container import ApplicationContainer

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
from application.structured_output.generator import StructuredOutputGenerator
from application.structured_output.parser import StructuredOutputParser
from application.services.artifact_service import ArtifactService
from application.services.execution_log_service import ExecutionLogService
from application.services.knowledge_service import KnowledgeService
from application.services.project_service import ProjectService
from application.services.durable_workflow_service import DurableWorkflowService
from application.services.workflow_service import WorkflowService
from application.runtime.durable_execution_policy import (
    supports_durable_workflow_execution,
)
from infrastructure.persistence.persistence_factory import build_persistence_bundle

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
    return create_application_container(config=config, overrides=overrides).agency


def create_application_container(
    config: ApplicationConfig | None = None,
    overrides: ApplicationOverrides | None = None,
) -> ApplicationContainer:
    """
    Composition Root for AI Research OS.

    Builds the application object graph and returns the full container
    for HTTP and other entry points.
    """
    config = config or ApplicationConfig()
    overrides = overrides or ApplicationOverrides()

    registry = overrides.registry or Registry()

    persistence = build_persistence_bundle(
        persistence_backend=config.persistence_backend,
        projects_root=config.projects_root,
        database_url=config.database_url,
    )

    project_repository = overrides.project_repository or persistence.project_repository

    project_factory = ProjectFactory()

    project_service = overrides.project_service or ProjectService(
        project_factory=project_factory,
        project_repository=project_repository,
    )

    workflow_run_factory = WorkflowRunFactory(
        task_factory=TaskFactory(),
    )

    workflow_service = WorkflowService(
        workflow_template_repository=persistence.workflow_template_repository,
        workflow_run_repository=persistence.workflow_run_repository,
        workflow_run_factory=workflow_run_factory,
    )

    artifact_service = ArtifactService(
        artifact_repository=persistence.artifact_repository,
    )

    knowledge_service = KnowledgeService(
        knowledge_repository=persistence.knowledge_repository,
    )

    execution_log_service = ExecutionLogService(
        execution_log_store=persistence.execution_log_store,
    )

    llm_client = overrides.llm_client or _create_llm_client(config)

    executor_catalog = ExecutorCatalog.from_capabilities(
        AGENT_EXECUTOR_CAPABILITIES,
    )

    template_loader = FileTemplateLoader()
    prompt_renderer = PythonFormatPromptRenderer()
    planner_prompt_builder = PlannerPromptBuilder(
        template_loader=template_loader,
        prompt_renderer=prompt_renderer,
        executor_catalog=executor_catalog,
    )

    workflow_template_mapper = ResearchPlanWorkflowTemplateMapper()

    structured_output_parser = StructuredOutputParser()
    planner_payload_contract = PlannerPayloadContract(
        executor_catalog=executor_catalog,
        response_parser=PlannerResponseParser(),
    )
    structured_output_generator = StructuredOutputGenerator(
        llm_client=llm_client,
        parser=structured_output_parser,
        executor_catalog=executor_catalog,
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
            structured_output_generator=structured_output_generator,
            payload_contract=planner_payload_contract,
        ).create()

    agent_executors = {
        "planner": PlannerExecutor(agent=planner_agent),
        "search": AgentExecutor(agent=SearchAgent()),
        "analysis": AgentExecutor(agent=AnalysisAgent()),
        "report": AgentExecutor(agent=ReportAgent()),
        "proposal": AgentExecutor(agent=ProposalAgent()),
    }

    _ensure_executor_catalog_matches_registry(
        executor_catalog,
        agent_executors,
    )

    agent_loader = AgentLoader(
        registry=registry,
        executors=agent_executors,
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

    durable_workflow_service: DurableWorkflowService | None = None
    if supports_durable_workflow_execution(config):
        durable_workflow_service = DurableWorkflowService(
            workflow_service=workflow_service,
            project_service=project_service,
            execution_log_store=persistence.execution_log_store,
            workflow_engine=workflow_engine,
        )

    agency = Agency(
        agent_loader=agent_loader,
        project_service=project_service,
        planner_agent=planner_agent,
        workflow_run_factory=workflow_run_factory,
        workflow_engine=workflow_engine,
        durable_workflow_service=durable_workflow_service,
    )

    shutdown_callbacks: list = []
    readiness_check = _build_readiness_check(
        config=config,
        persistence_engine=persistence.engine,
        shutdown_callbacks=shutdown_callbacks,
    )

    return ApplicationContainer(
        config=config,
        agency=agency,
        project_service=project_service,
        workflow_service=workflow_service,
        artifact_service=artifact_service,
        knowledge_service=knowledge_service,
        execution_log_service=execution_log_service,
        durable_workflow_service=durable_workflow_service,
        readiness_check=readiness_check,
        _shutdown_callbacks=shutdown_callbacks,
    )


def _build_readiness_check(
    *,
    config: ApplicationConfig,
    persistence_engine: object | None,
    shutdown_callbacks: list,
):
    if config.persistence_backend != "postgresql":
        return lambda: (True, "ready")

    if persistence_engine is None:
        return lambda: (False, "postgresql_engine_unavailable")

    from infrastructure.persistence.postgresql.readiness import (
        build_postgresql_readiness_check,
        resolve_expected_alembic_head,
    )

    expected_revision = resolve_expected_alembic_head()
    return build_postgresql_readiness_check(
        persistence_engine,
        expected_revision,
        shutdown_callbacks,
    )


def _ensure_executor_catalog_matches_registry(
    executor_catalog: ExecutorCatalog,
    agent_executors: dict,
) -> None:
    catalog_ids = set(executor_catalog.executor_ids)
    registry_ids = set(agent_executors)

    if catalog_ids != registry_ids:
        missing_in_registry = catalog_ids - registry_ids
        missing_in_catalog = registry_ids - catalog_ids

        raise ValueError(
            "Executor catalog and agent registry are out of sync. "
            f"missing_in_registry={sorted(missing_in_registry)} "
            f"missing_in_catalog={sorted(missing_in_catalog)}"
        )


def _create_llm_client(config: ApplicationConfig):
    from infrastructure.llm.llm_configuration import LLMConfiguration
    from infrastructure.llm.openai_client import OpenAIClient

    llm_configuration = LLMConfiguration(
        model=config.llm_model,
        max_tokens=config.llm_max_tokens,
    )

    return OpenAIClient(configuration=llm_configuration)

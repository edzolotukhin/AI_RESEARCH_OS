from __future__ import annotations

from application.config import ApplicationConfig, ApplicationOverrides
from application.executor_resolver import ExecutorResolver
from application.factories.research_design_factory import ResearchDesignFactory
from application.parsers.research_design_parser import ResearchDesignParser
from application.planner.research_design_workflow_mapper import (
    ResearchDesignWorkflowMapper,
)
from application.planner.design_service import PlannerDesignServiceImpl
from application.planner.research_design_payload_contract import (
    ResearchDesignPayloadContract,
)
from application.planner.executor_catalog import ExecutorCatalog
from application.planner.executor_definitions import AGENT_EXECUTOR_CAPABILITIES
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

from agents.planner.planner_agent_factory import PlannerAgentFactory
from agents.planner.planner_executor import PlannerExecutor
from agents.proposal.proposal_agent import ProposalAgent

from application.executors.agent_executor import AgentExecutor
from application.executors.search_executor import SearchExecutor
from application.executors.stage_executors import (
    DeterministicStageExecutor,
    UnimplementedCapabilityExecutor,
)

from domain.factories.project_factory import ProjectFactory
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory

from application.services.source_service import SourceService
from application.sources.search_factory import build_search_executor
from application.structured_output.correction_prompt import (
    RESEARCH_DESIGN_PAYLOAD_SCHEMA,
)
from application.structured_output.generator import StructuredOutputGenerator
from application.structured_output.parser import StructuredOutputParser
from application.services.artifact_service import ArtifactService
from application.services.execution_log_service import ExecutionLogService
from application.services.knowledge_service import KnowledgeService
from application.services.project_service import ProjectService
from application.services.durable_workflow_service import DurableWorkflowService
from application.services.workflow_service import WorkflowService
from application.services.research_submission_service import ResearchSubmissionService
from application.services.worker_execution_service import WorkerExecutionService
from application.services.authentication_service import AuthenticationService
from application.services.authorization_service import AuthorizationService
from application.execution.lease_config import LeaseConfig
from application.runtime.background_execution_capability import (
    resolve_background_execution_capability,
)
from application.runtime.durable_execution_policy import (
    supports_durable_workflow_execution,
)
from infrastructure.persistence.noop_run_queue import NoOpRunQueue

from infrastructure.persistence.persistence_factory import build_persistence_bundle
from infrastructure.security.sha256_api_key_material_provider import (
    Sha256ApiKeyMaterialProvider,
)

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
    config = config or ApplicationConfig.from_env()
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

    source_repository = overrides.source_repository or persistence.source_repository
    source_service = SourceService(source_repository=source_repository)

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

    workflow_template_mapper = ResearchDesignWorkflowMapper()

    structured_output_parser = StructuredOutputParser()
    planner_payload_contract = ResearchDesignPayloadContract(
        response_parser=ResearchDesignParser(),
    )
    structured_output_generator = StructuredOutputGenerator(
        llm_client=llm_client,
        parser=structured_output_parser,
        executor_catalog=executor_catalog,
        payload_schema=RESEARCH_DESIGN_PAYLOAD_SCHEMA,
    )

    planner_design_service = PlannerDesignServiceImpl(
        response_parser=ResearchDesignParser(),
        design_factory=ResearchDesignFactory(),
    )

    if overrides.planner_agent is not None:
        planner_agent = overrides.planner_agent
    else:
        planner_agent = PlannerAgentFactory(
            planner_design_service=planner_design_service,
            workflow_mapper=workflow_template_mapper,
            prompt_builder=planner_prompt_builder,
            structured_output_generator=structured_output_generator,
            payload_contract=planner_payload_contract,
        ).create()

    agent_executors = _build_agent_executors(
        config=config,
        overrides=overrides,
        planner_agent=planner_agent,
        source_repository=source_repository,
    )

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
    worker_execution_service: WorkerExecutionService | None = None
    background_execution = resolve_background_execution_capability(
        config,
        execution_port_available=persistence.workflow_run_execution_repository
        is not None,
    )
    lease_config = LeaseConfig.from_env()
    if supports_durable_workflow_execution(config):
        durable_workflow_service = DurableWorkflowService(
            workflow_service=workflow_service,
            project_service=project_service,
            execution_log_store=persistence.execution_log_store,
            workflow_engine=workflow_engine,
            execution_port=persistence.workflow_run_execution_repository,
            run_queue=NoOpRunQueue(),
            lease_config=lease_config,
        )
        if background_execution.in_process_worker:
            worker_execution_service = WorkerExecutionService(
                durable_workflow_service=durable_workflow_service,
                execution_port=persistence.workflow_run_execution_repository,
                lease_config=lease_config,
            )

    research_submission_service: ResearchSubmissionService | None = None
    if persistence.research_submission_repository is not None:
        research_submission_service = ResearchSubmissionService(
            submission_repository=persistence.research_submission_repository,
        )

    authentication_service: AuthenticationService | None = None
    authorization_service: AuthorizationService | None = None
    if persistence.api_key_repository is not None:
        material_provider = Sha256ApiKeyMaterialProvider()
        authentication_service = AuthenticationService(
            api_key_repository=persistence.api_key_repository,
            material_provider=material_provider,
        )
        authorization_service = AuthorizationService(
            project_service=project_service,
            workflow_service=workflow_service,
            artifact_service=artifact_service,
            source_service=source_service,
        )

    agency = Agency(
        agent_loader=agent_loader,
        project_service=project_service,
        planner_agent=planner_agent,
        workflow_run_factory=workflow_run_factory,
        workflow_engine=workflow_engine,
        durable_workflow_service=durable_workflow_service,
        background_execution_enabled=background_execution.http_submission,
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
        source_service=source_service,
        execution_log_service=execution_log_service,
        durable_workflow_service=durable_workflow_service,
        worker_execution_service=worker_execution_service,
        research_submission_service=research_submission_service,
        authentication_service=authentication_service,
        authorization_service=authorization_service,
        background_execution=background_execution,
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


def _build_agent_executors(
    *,
    config: ApplicationConfig,
    overrides: ApplicationOverrides,
    planner_agent,
    source_repository,
) -> dict:
    use_deterministic_stages = (
        overrides.deterministic_stage_executors
        if overrides.deterministic_stage_executors is not None
        else config.deterministic_stage_executors
    )

    executors = {
        "planner": PlannerExecutor(agent=planner_agent),
        "proposal": AgentExecutor(agent=ProposalAgent()),
    }

    if use_deterministic_stages:
        for executor_id, stage_key in (
            ("search", "collect_sources"),
            ("analysis", "analyze"),
            ("report", "write_report"),
        ):
            executors[executor_id] = DeterministicStageExecutor(stage_key=stage_key)
        return executors

    executors["search"] = build_search_executor(
        config=config,
        overrides=overrides,
        source_repository=source_repository,
    )
    executors["analysis"] = UnimplementedCapabilityExecutor(
        capability="analysis",
        stage="analyze",
    )
    executors["report"] = UnimplementedCapabilityExecutor(
        capability="report",
        stage="write_report",
    )
    return executors


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
    import os

    if os.environ.get("DETERMINISTIC_PLANNER", "").lower() in {"1", "true", "yes"}:
        from infrastructure.llm.deterministic_llm_client import DeterministicLLMClient

        return DeterministicLLMClient()

    from infrastructure.llm.llm_configuration import LLMConfiguration
    from infrastructure.llm.openai_client import OpenAIClient

    llm_configuration = LLMConfiguration(
        model=config.llm_model,
        max_tokens=config.llm_max_tokens,
    )

    return OpenAIClient(configuration=llm_configuration)

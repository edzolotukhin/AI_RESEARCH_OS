from __future__ import annotations

from application.config import ApplicationConfig, ApplicationOverrides
from application.executor_resolver import ExecutorResolver
from application.factories.research_design_factory import ResearchDesignFactory
from application.parsers.research_design_parser import ResearchDesignParser
from application.planner.research_design_workflow_mapper import (
    ResearchDesignWorkflowMapper,
)
from application.planner.design_service import PlannerDesignServiceImpl
from application.planner.planner_bounds import PlannerBounds
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
from application.quantitative.workflow import QuantitativeStageExecutor
from application.quantitative.state_persistence import QuantitativeStateService
from application.quantitative.stage_service_factory import (
    QuantitativeStageServiceFactory,
    QuantitativeWorkflowContextServiceResolver,
)
from application.quantitative.ui_service import QuantitativeUiService

from agency.agency import Agency

from application.container import ApplicationContainer

from agents.planner.planner_agent_factory import PlannerAgentFactory
from agents.planner.planner_executor import PlannerExecutor
from agents.proposal.proposal_agent import ProposalAgent

from application.executors.agent_executor import AgentExecutor
from application.executors.evidence_executor import EvidenceExecutor
from application.executors.search_executor import SearchExecutor
from application.executors.stage_executors import (
    DeterministicStageExecutor,
    UnimplementedCapabilityExecutor,
)

from domain.factories.project_factory import ProjectFactory
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory

from application.services.evidence_service import EvidenceService
from application.services.finding_service import FindingService, InsightService
from application.services.report_query_service import ReportQueryService
from application.services.review_query_service import ReviewQueryService
from application.query.research_run_result_query_service import (
    ResearchRunResultQueryService,
)
from application.query.research_status_query_service import (
    ResearchStatusQueryService,
)
from application.services.source_service import SourceService
from application.evidence.evidence_factory import build_evidence_executor
from application.analysis.analysis_factory import build_analysis_executor
from application.report.report_factory import build_report_executor
from application.review.review_factory import build_review_executor
from application.research_quality.research_quality_factory import (
    build_research_readiness_executor,
)
from application.sources.search_factory import build_search_executor
from application.structured_output.correction_prompt import (
    RESEARCH_DESIGN_PAYLOAD_SCHEMA,
)
from application.structured_output.generation_policy import StructuredGenerationPolicy
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
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from infrastructure.quantitative.importers import SavPyreadstatAdapter, XlsxOpenpyxlAdapter
from infrastructure.quantitative.storage.protected_file_dataset_storage import ProtectedFileDatasetStorage

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
    evidence_repository = (
        overrides.evidence_repository or persistence.evidence_repository
    )
    evidence_service = EvidenceService(evidence_repository=evidence_repository)
    finding_repository = (
        overrides.finding_repository or persistence.finding_repository
    )
    insight_repository = (
        overrides.insight_repository or persistence.insight_repository
    )
    report_repository = (
        overrides.report_repository or persistence.report_repository
    )
    review_repository = (
        overrides.review_repository or persistence.review_repository
    )
    finding_service = FindingService(finding_repository=finding_repository)
    insight_service = InsightService(insight_repository=insight_repository)
    report_query_service = ReportQueryService(report_repository=report_repository)
    review_query_service = ReviewQueryService(review_repository=review_repository)
    research_run_result_query_service = ResearchRunResultQueryService(
        workflow_run_repository=persistence.workflow_run_repository,
        source_repository=source_repository,
        evidence_repository=evidence_repository,
        finding_repository=finding_repository,
        insight_repository=insight_repository,
        report_repository=report_repository,
        review_repository=review_repository,
        artifact_repository=persistence.artifact_repository,
    )
    research_status_query_service = ResearchStatusQueryService(
        workflow_run_repository=persistence.workflow_run_repository,
        research_run_result_query_service=research_run_result_query_service,
    )

    execution_log_service = ExecutionLogService(
        execution_log_store=persistence.execution_log_store,
    )

    from application.llm.stage_llm_clients import resolve_stage_llm_clients

    stage_llm_clients = resolve_stage_llm_clients(config, overrides)
    planner_llm_client = stage_llm_clients.planner

    executor_catalog = ExecutorCatalog.from_capabilities(
        AGENT_EXECUTOR_CAPABILITIES,
    )

    planner_bounds = PlannerBounds.from_env()

    template_loader = FileTemplateLoader()
    prompt_renderer = PythonFormatPromptRenderer()
    planner_prompt_builder = PlannerPromptBuilder(
        template_loader=template_loader,
        prompt_renderer=prompt_renderer,
        executor_catalog=executor_catalog,
        bounds=planner_bounds,
    )

    workflow_template_mapper = ResearchDesignWorkflowMapper()

    structured_output_parser = StructuredOutputParser()
    planner_payload_contract = ResearchDesignPayloadContract(
        response_parser=ResearchDesignParser(),
        bounds=planner_bounds,
    )
    structured_output_generator = StructuredOutputGenerator(
        llm_client=planner_llm_client,
        parser=structured_output_parser,
        executor_catalog=executor_catalog,
        payload_schema=RESEARCH_DESIGN_PAYLOAD_SCHEMA,
        generation_policy=StructuredGenerationPolicy(
            reasoning_effort=config.planner_reasoning_effort,
            max_output_tokens=config.planner_max_output_tokens,
            escalation_reasoning_effort="minimal",
            escalation_max_output_tokens=max(
                config.planner_max_output_tokens,
                8192,
            ),
        ),
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
        evidence_repository=evidence_repository,
        finding_repository=finding_repository,
        insight_repository=insight_repository,
        report_repository=report_repository,
        review_repository=review_repository,
        artifact_repository=persistence.artifact_repository,
        stage_llm_clients=stage_llm_clients,
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

    # Q1-16 registers only the methodology bridge. Dataset/analysis services
    # are supplied run-scoped and keep protected respondent data behind QL ports.
    if not registry.tools.exists("quantitative-stage"):
        registry.tools.register("quantitative-stage", QuantitativeStageExecutor())

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

    quantitative_state_service = None
    quantitative_stage_service_factory = None
    quantitative_generators = None
    quantitative_generation_mode = None
    quantitative_storage_factory = None
    quantitative_importers = None
    if persistence.quantitative_state_repository is not None:
        from application.structured_output.json_validator import JsonValidator
        from application.llm.stage_llm_clients import create_quantitative_live_llm_client

        use_offline_quantitative = (
            overrides.deterministic_stage_executors
            if overrides.deterministic_stage_executors is not None
            else config.deterministic_stage_executors
        )
        if use_offline_quantitative:
            from application.quantitative.offline_generators import (
                OfflineFindingGenerator,
                OfflineInsightGenerator,
                OfflineReportGenerator,
            )

            quantitative_generators = (
                OfflineFindingGenerator(),
                OfflineInsightGenerator(),
                OfflineReportGenerator(),
            )
            quantitative_generation_mode = "offline"
        else:
            from infrastructure.quantitative.llm_generators import (
                LLMQuantitativeFindingGenerator,
                LLMQuantitativeInsightGenerator,
                LLMQuantitativeReportGenerator,
            )

            quantitative_client = create_quantitative_live_llm_client(
                config,
                overrides.quantitative_llm_client,
            )
            validator = JsonValidator()
            generator_options = {
                "llm_client": quantitative_client,
                "json_validator": validator,
                "max_output_tokens": config.quantitative_max_output_tokens,
                "reasoning_effort": config.quantitative_reasoning_effort,
            }
            quantitative_generators = (
                LLMQuantitativeFindingGenerator(**generator_options),
                LLMQuantitativeInsightGenerator(**generator_options),
                LLMQuantitativeReportGenerator(**generator_options),
            )
            quantitative_generation_mode = "production"
        digest_provider = Sha256DigestProvider()
        quantitative_state_service = QuantitativeStateService(
            repository=persistence.quantitative_state_repository,
            digest_provider=digest_provider,
        )
        from application.quantitative.research_design_authority import QuantitativeResearchDesignService
        from application.quantitative.questionnaire_authority import QuantitativeQuestionnaireService
        from application.quantitative.measurement_reconciliation import QuantitativeMeasurementReconciliationService
        from application.quantitative.analysis_planning import QuantitativeAnalysisPlanService
        from infrastructure.persistence.quantitative_research_design_repository import QLQuantitativeResearchDesignRepository
        from infrastructure.persistence.quantitative_questionnaire_repository import QLQuantitativeQuestionnaireRepository
        from infrastructure.persistence.quantitative_measurement_reconciliation_repository import QLQuantitativeMeasurementReconciliationRepository
        from infrastructure.persistence.quantitative_analysis_plan_repository import QLQuantitativeAnalysisPlanRepository
        from infrastructure.persistence.quantitative_analysis_execution_repository import QLQuantitativeAnalysisExecutionRepository
        from infrastructure.persistence.quantitative_finding_lineage_repository import QLQuantitativeFindingLineageRepository
        from infrastructure.persistence.quantitative_insight_lineage_repository import QLQuantitativeInsightLineageRepository
        quantitative_design_service=QuantitativeResearchDesignService(repository=QLQuantitativeResearchDesignRepository(quantitative_state_service),digest_provider=digest_provider)
        quantitative_questionnaire_service=QuantitativeQuestionnaireService(repository=QLQuantitativeQuestionnaireRepository(quantitative_state_service),research_design_service=quantitative_design_service,digest_provider=digest_provider)
        quantitative_reconciliation_service=QuantitativeMeasurementReconciliationService(repository=QLQuantitativeMeasurementReconciliationRepository(quantitative_state_service),questionnaire_service=quantitative_questionnaire_service,digest_provider=digest_provider)
        quantitative_analysis_plan_service=QuantitativeAnalysisPlanService(repository=QLQuantitativeAnalysisPlanRepository(quantitative_state_service),research_design_service=quantitative_design_service,questionnaire_service=quantitative_questionnaire_service,reconciliation_service=quantitative_reconciliation_service,digest_provider=digest_provider)
        protected_root = (
            config.quantitative_protected_storage_root
            or f"{config.projects_root}/.quantitative-protected"
        )
        quantitative_storage_factory = lambda project_id, run_id: (
            ProtectedFileDatasetStorage(
                root=protected_root,
                project_id=project_id,
                run_id=run_id,
                digest_provider=digest_provider,
            )
        )
        quantitative_importers = (SavPyreadstatAdapter(), XlsxOpenpyxlAdapter())
        quantitative_stage_service_factory = QuantitativeStageServiceFactory(
            state_service=quantitative_state_service,
            digest_provider=digest_provider,
            storage_factory=quantitative_storage_factory,
            importers=quantitative_importers,
            finding_generator=quantitative_generators[0],
            insight_generator=quantitative_generators[1],
            report_generator=quantitative_generators[2],
            generation_mode=quantitative_generation_mode,
            analysis_plan_service=quantitative_analysis_plan_service,
            analysis_execution_repository_factory=lambda: QLQuantitativeAnalysisExecutionRepository(quantitative_state_service),
            finding_lineage_repository_factory=lambda: QLQuantitativeFindingLineageRepository(quantitative_state_service),
            insight_lineage_repository_factory=lambda: QLQuantitativeInsightLineageRepository(quantitative_state_service),
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
            context_service_resolver=(
                QuantitativeWorkflowContextServiceResolver(
                    quantitative_stage_service_factory
                )
                if quantitative_stage_service_factory is not None
                else None
            ),
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
            evidence_service=evidence_service,
            finding_service=finding_service,
            insight_service=insight_service,
            report_query_service=report_query_service,
            review_query_service=review_query_service,
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

    quantitative_ui_service = None
    if quantitative_stage_service_factory is not None:
        quantitative_ui_service = QuantitativeUiService(
            project_service=project_service,
            workflow_service=workflow_service,
            state_service=quantitative_state_service,
            digest_provider=digest_provider,
            storage_factory=quantitative_storage_factory,
            importers=quantitative_importers,
            finding_generator=quantitative_generators[0],
            insight_generator=quantitative_generators[1],
            report_generator=quantitative_generators[2],
            generation_mode=quantitative_generation_mode,
            stage_service_factory=quantitative_stage_service_factory,
            durable_workflow_service=(
                durable_workflow_service
                if background_execution.multi_process_worker
                else None
            ),
        )

    return ApplicationContainer(
        config=config,
        agency=agency,
        project_service=project_service,
        workflow_service=workflow_service,
        artifact_service=artifact_service,
        knowledge_service=knowledge_service,
        source_service=source_service,
        evidence_service=evidence_service,
        finding_service=finding_service,
        insight_service=insight_service,
        report_query_service=report_query_service,
        review_query_service=review_query_service,
        research_run_result_query_service=research_run_result_query_service,
        research_status_query_service=research_status_query_service,
        execution_log_service=execution_log_service,
        durable_workflow_service=durable_workflow_service,
        worker_execution_service=worker_execution_service,
        research_submission_service=research_submission_service,
        authentication_service=authentication_service,
        authorization_service=authorization_service,
        background_execution=background_execution,
        readiness_check=readiness_check,
        quantitative_ui_service=quantitative_ui_service,
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
    evidence_repository,
    finding_repository,
    insight_repository,
    report_repository,
    review_repository,
    artifact_repository,
    stage_llm_clients,
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
            ("evidence", "extract_evidence"),
            ("research_quality", "assess_research_readiness"),
            ("analysis", "analyze"),
            ("report", "write_report"),
            ("review", "review_report"),
        ):
            if executor_id == "research_quality":
                from application.executors.deterministic_research_readiness_executor import (
                    DeterministicResearchReadinessExecutor,
                )

                executors[executor_id] = DeterministicResearchReadinessExecutor()
            else:
                executors[executor_id] = DeterministicStageExecutor(stage_key=stage_key)
        return executors

    executors["search"] = build_search_executor(
        config=config,
        overrides=overrides,
        source_repository=source_repository,
    )
    executors["evidence"] = build_evidence_executor(
        config=config,
        overrides=overrides,
        evidence_repository=evidence_repository,
        source_repository=source_repository,
        llm_client=stage_llm_clients.evidence,
    )
    executors["research_quality"] = build_research_readiness_executor(
        config=config,
        overrides=overrides,
        evidence_repository=evidence_repository,
        source_repository=source_repository,
        llm_client=stage_llm_clients.evidence,
    )
    executors["analysis"] = build_analysis_executor(
        config=config,
        overrides=overrides,
        evidence_repository=evidence_repository,
        finding_repository=finding_repository,
        insight_repository=insight_repository,
        llm_client=stage_llm_clients.analysis,
    )
    executors["report"] = (
        overrides.report_executor
        if overrides.report_executor is not None
        else build_report_executor(
            config=config,
            overrides=overrides,
            finding_repository=finding_repository,
            insight_repository=insight_repository,
            evidence_repository=evidence_repository,
            source_repository=source_repository,
            report_repository=report_repository,
            artifact_repository=artifact_repository,
            llm_client=stage_llm_clients.report,
        )
    )
    executors["review"] = (
        overrides.review_executor
        if overrides.review_executor is not None
        else build_review_executor(
            config=config,
            overrides=overrides,
            finding_repository=finding_repository,
            insight_repository=insight_repository,
            evidence_repository=evidence_repository,
            source_repository=source_repository,
            report_repository=report_repository,
            artifact_repository=artifact_repository,
            review_repository=review_repository,
            llm_client=stage_llm_clients.review,
        )
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
    """
    Legacy live LLM client constructor.

    DETERMINISTIC_PLANNER no longer affects this function (P1-08.2).
    Prefer resolve_stage_llm_clients() for stage-scoped composition.
    """
    from application.llm.stage_llm_clients import create_live_llm_client

    return create_live_llm_client(config)

from __future__ import annotations

from application.config import ApplicationConfig, ApplicationOverrides
from application.executors.deterministic_research_readiness_executor import (
    DeterministicResearchReadinessExecutor,
)
from application.executors.research_readiness_executor import ResearchReadinessExecutor
from application.ports.evidence_ports import EvidenceRepository
from application.ports.research_quality_ports import ResearchSufficiencyEvaluator
from application.ports.source_ports import SourceRepository
from application.research_quality.deterministic_sufficiency_evaluator import (
    DeterministicSufficiencyEvaluator,
)
from application.research_quality.hybrid_sufficiency_evaluator import (
    HybridResearchSufficiencyEvaluator,
)
from application.research_quality.production_targeted_research_runner import (
    ProductionTargetedResearchRunner,
)
from application.research_quality.research_loop_service import ResearchLoopService
from application.research_quality.research_readiness_service import ResearchReadinessService
from application.research_quality.targeted_research_bounds import TargetedResearchBounds
from application.research_quality.targeted_search_query_builder import (
    TargetedSearchQueryBuilder,
)
from application.sources.search_factory import build_source_acquisition_service
from application.evidence.evidence_factory import build_evidence_extraction_service


def build_research_sufficiency_evaluator(
    *,
    config: ApplicationConfig,
    overrides: ApplicationOverrides,
    llm_client,
) -> ResearchSufficiencyEvaluator:
    if overrides.research_sufficiency_evaluator is not None:
        return overrides.research_sufficiency_evaluator

    provider = config.research_sufficiency_assessor.lower()
    if provider == "deterministic":
        from application.research_quality.deterministic_research_sufficiency_evaluator import (
            DeterministicResearchSufficiencyEvaluator,
        )

        return DeterministicResearchSufficiencyEvaluator()
    if provider == "llm":
        if llm_client is None:
            raise ValueError(
                "LLM client is required for RESEARCH_SUFFICIENCY_ASSESSOR=llm",
            )
        from infrastructure.research_quality.llm_semantic_sufficiency_assessor import (
            LlmSemanticSufficiencyAssessor,
        )

        return HybridResearchSufficiencyEvaluator(
            deterministic_evaluator=DeterministicSufficiencyEvaluator(),
            semantic_assessor=LlmSemanticSufficiencyAssessor(
                llm_client=llm_client,
                max_output_tokens=config.sufficiency_max_output_tokens,
                reasoning_effort=config.sufficiency_reasoning_effort,
            ),
        )
    raise ValueError(
        f"Unsupported RESEARCH_SUFFICIENCY_ASSESSOR: {provider!r}. "
        "Expected one of: llm, deterministic.",
    )


def build_research_readiness_service(
    *,
    config: ApplicationConfig,
    overrides: ApplicationOverrides,
    evidence_repository: EvidenceRepository,
    source_repository: SourceRepository,
    llm_client,
) -> ResearchReadinessService:
    evaluator = build_research_sufficiency_evaluator(
        config=config,
        overrides=overrides,
        llm_client=llm_client,
    )
    bounds = TargetedResearchBounds.from_config(config)
    runner = overrides.targeted_research_runner
    if runner is None:
        source_acquisition = build_source_acquisition_service(
            config=config,
            overrides=overrides,
            source_repository=source_repository,
            evidence_repository=evidence_repository,
        )
        evidence_extraction = build_evidence_extraction_service(
            config=config,
            overrides=overrides,
            evidence_repository=evidence_repository,
            source_repository=source_repository,
            llm_client=llm_client,
        )
        runner = ProductionTargetedResearchRunner(
            query_builder=TargetedSearchQueryBuilder(),
            source_acquisition=source_acquisition,
            evidence_extraction=evidence_extraction,
            bounds=bounds,
            config=config,
        )

    loop_service = ResearchLoopService(
        runner=runner,
        bounds=bounds,
        evaluator=evaluator,
        evidence_repository=evidence_repository,
        source_repository=source_repository,
    )
    return ResearchReadinessService(
        evaluator=evaluator,
        evidence_repository=evidence_repository,
        loop_service=loop_service,
    )


def build_research_readiness_executor(
    *,
    config: ApplicationConfig,
    overrides: ApplicationOverrides,
    evidence_repository: EvidenceRepository,
    source_repository: SourceRepository,
    llm_client,
) -> ResearchReadinessExecutor | DeterministicResearchReadinessExecutor:
    if overrides.research_readiness_executor is not None:
        return overrides.research_readiness_executor

    use_deterministic = (
        overrides.deterministic_stage_executors
        if overrides.deterministic_stage_executors is not None
        else config.deterministic_stage_executors
    )
    if use_deterministic:
        return DeterministicResearchReadinessExecutor()

    return ResearchReadinessExecutor(
        research_readiness_service=build_research_readiness_service(
            config=config,
            overrides=overrides,
            evidence_repository=evidence_repository,
            source_repository=source_repository,
            llm_client=llm_client,
        ),
    )

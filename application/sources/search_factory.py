from __future__ import annotations

from application.config import ApplicationConfig, ApplicationOverrides
from application.executors.search_executor import SearchExecutor
from application.ports.evidence_ports import EvidenceRepository
from application.ports.source_ports import SearchProvider, SourceRepository, SourceRetriever
from application.sources.search_query_builder import SearchQueryBuilder
from application.sources.source_acquisition_service import SourceAcquisitionService
from application.sources.source_budget import SourceAcquisitionBudget
from infrastructure.retrieval.http_source_retriever import (
    HttpRetrievalLimits,
    HttpSourceRetriever,
)
from infrastructure.search.deterministic_search_adapter import (
    DeterministicSearchProvider,
    DeterministicSourceRetriever,
)
from infrastructure.search.tavily_search_provider import TavilySearchProvider


def build_search_provider(
    config: ApplicationConfig,
    overrides: ApplicationOverrides,
) -> SearchProvider:
    if overrides.search_provider is not None:
        return overrides.search_provider

    provider_name = config.search_provider.lower()
    if provider_name == "deterministic":
        return DeterministicSearchProvider()
    if provider_name == "tavily":
        return TavilySearchProvider(api_key=config.search_api_key)
    raise ValueError(
        f"Unsupported SEARCH_PROVIDER: {provider_name!r}. "
        "Expected one of: tavily, deterministic.",
    )


def build_source_retriever(
    config: ApplicationConfig,
    overrides: ApplicationOverrides,
) -> SourceRetriever:
    if overrides.source_retriever is not None:
        return overrides.source_retriever

    if config.search_provider.lower() == "deterministic":
        return DeterministicSourceRetriever()
    budget = SourceAcquisitionBudget.from_config(config)
    return HttpSourceRetriever(
        limits=HttpRetrievalLimits(
            timeout_seconds=budget.http_timeout_seconds,
            max_redirects=budget.max_redirects,
            max_body_bytes=budget.max_body_bytes,
        ),
        dns_timeout_seconds=budget.dns_timeout_seconds,
    )


def build_source_acquisition_service(
    *,
    config: ApplicationConfig,
    overrides: ApplicationOverrides,
    source_repository: SourceRepository,
    evidence_repository: EvidenceRepository | None = None,
) -> SourceAcquisitionService:
    budget = SourceAcquisitionBudget.from_config(config)
    return SourceAcquisitionService(
        search_provider=build_search_provider(config, overrides),
        source_retriever=build_source_retriever(config, overrides),
        source_repository=source_repository,
        query_builder=SearchQueryBuilder(
            max_results=budget.max_candidates_per_query,
        ),
        budget=budget,
        evidence_repository=evidence_repository,
    )


def build_search_executor(
    *,
    config: ApplicationConfig,
    overrides: ApplicationOverrides,
    source_repository: SourceRepository,
) -> SearchExecutor:
    return SearchExecutor(
        source_acquisition_service=build_source_acquisition_service(
            config=config,
            overrides=overrides,
            source_repository=source_repository,
        ),
    )

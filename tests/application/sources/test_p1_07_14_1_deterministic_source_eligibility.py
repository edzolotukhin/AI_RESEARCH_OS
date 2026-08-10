"""P1-07.14.1 deterministic source eligibility and targeted exhaustion."""

from __future__ import annotations

import ast
import inspect
import unittest
from datetime import datetime, timezone
from pathlib import Path

from domain.evidence.evidence import Evidence
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.project import Project
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.search_query import SearchQuery
from domain.sources.source import Source
from domain.sources.source_candidate import SourceCandidate
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template import WorkflowTemplate

from application.ports.source_ports import SearchProvider, SourceRetriever
from application.sources.deterministic_source_relevance import (
    ACTION_EXHAUSTED,
    ACTION_FETCH_FAILED,
    ACTION_REJECTED,
    ACTION_SELECTED,
    ELIGIBILITY_DIRECT,
    ELIGIBILITY_INELIGIBLE,
    ELIGIBILITY_PROXY,
    ELIGIBILITY_UNSCORED,
    GEO_DIRECT,
    GEO_PROXY,
    GEO_UNRELATED,
    build_relevance_context,
    evaluate_candidate,
)
from application.sources.search_query_builder import SearchQueryBuilder
from application.sources.source_acquisition_service import SourceAcquisitionService
from application.sources.source_budget import SourceAcquisitionBudget
from application.sources.source_need_exhaustion import (
    exhausted_canonical_urls_for_need,
    work_item_is_valid_zero_yield,
)
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)
from infrastructure.search.tavily_search_provider import TavilySearchProvider
from runtime.workflow_context import WorkflowContext

REPO_ROOT = Path(__file__).resolve().parents[3]


def _ee(**overrides) -> EvidenceExpectation:
    payload = {
        "nature": EvidenceNature.QUALITATIVE,
        "required_aspects": ("quality_attributes", "procurement_process"),
        "geography": "Kenya",
        "timeframe": "2024-2026",
        "requires_quantitative_evidence": False,
        "minimum_independent_sources": 2,
    }
    payload.update(overrides)
    return EvidenceExpectation(**payload)


def _design(
    *,
    rq_question: str,
    description: str,
    geography: str = "Kenya",
    timeframe: str = "2024-2026",
    expectation: EvidenceExpectation | None = ...,
    need_id: str = "IN1",
    rq_id: str = "RQ1",
) -> ResearchDesign:
    ee: EvidenceExpectation | None
    if expectation is ...:
        ee = _ee(geography=geography)
    else:
        ee = expectation
    return ResearchDesign(
        id="design-141",
        research_questions=(
            ResearchQuestion(id=rq_id, question=rq_question, objective_refs=()),
        ),
        information_needs=(
            InformationNeed(
                id=need_id,
                research_question_id=rq_id,
                description=description,
                geography=geography,
                timeframe=timeframe,
                evidence_expectation=ee,
            ),
        ),
    )


def _context(design: ResearchDesign, *, project_id: str = "project-141") -> WorkflowContext:
    template = WorkflowTemplate(
        id="template-141",
        name="Desk",
        task_definitions=[
            TaskDefinition(
                id="task-collect-evidence",
                name="Collect",
                executor_id="search",
                executor_type=ExecutorType.AGENT,
            ),
        ],
        research_design_snapshot=design,
    )
    run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
    run.id = "run-141"
    context = WorkflowContext(
        project=Project(id=project_id, name="Project"),
        workflow_template=template,
        workflow_run=run,
    )
    context.current_task = run.tasks[0]
    return context


def _candidate(
    *,
    url: str,
    title: str,
    snippet: str,
    rank: int,
    query_id: str = "sq-IN1",
) -> SourceCandidate:
    return SourceCandidate(
        provider="tavily",
        url=url,
        title=title,
        snippet=snippet,
        query_id=query_id,
        rank=rank,
    )


class _ScriptedProvider(SearchProvider):
    def __init__(self, candidates: list[SourceCandidate]) -> None:
        self.calls = 0
        self._candidates = candidates

    def search(self, query: SearchQuery) -> list[SourceCandidate]:
        self.calls += 1
        return [
            SourceCandidate(
                provider=item.provider,
                url=item.url,
                title=item.title,
                snippet=item.snippet,
                query_id=query.id,
                rank=item.rank,
                metadata=dict(item.metadata),
            )
            for item in self._candidates
        ]


class _RecordingRetriever(SourceRetriever):
    def __init__(self, *, fail_urls: frozenset[str] = frozenset()) -> None:
        self.fetched_urls: list[str] = []
        self._fail_urls = fail_urls

    def retrieve(self, candidate: SourceCandidate) -> Source:
        self.fetched_urls.append(candidate.url)
        now = datetime.now(timezone.utc).isoformat()
        if candidate.url in self._fail_urls:
            return Source(
                id="",
                project_id="",
                url=candidate.url,
                canonical_url=candidate.url,
                title=candidate.title,
                retrieved_at=now,
                retrieval_status=RetrievalStatus.FAILED,
                metadata={"failure_category": "http_error", "reason": "test fail"},
            )
        return Source(
            id="",
            project_id="",
            url=candidate.url,
            canonical_url=candidate.url,
            title=candidate.title,
            retrieved_at=now,
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text=f"Body for {candidate.title}",
        )


def _service(
    provider: SearchProvider,
    retriever: SourceRetriever,
    source_repo: InMemorySourceRepository | None = None,
    evidence_repo: InMemoryEvidenceRepository | None = None,
    *,
    max_sources_per_run: int = 18,
    min_successful: int = 1,
) -> tuple[SourceAcquisitionService, InMemorySourceRepository]:
    repository = source_repo or InMemorySourceRepository()
    service = SourceAcquisitionService(
        search_provider=provider,
        source_retriever=retriever,
        source_repository=repository,
        query_builder=SearchQueryBuilder(max_results=3),
        budget=SourceAcquisitionBudget(
            max_candidates_per_query=3,
            max_candidates_per_information_need=3,
            max_sources_per_run=max_sources_per_run,
            min_successful_sources=min_successful,
        ),
        evidence_repository=evidence_repo,
    )
    return service, repository


def _persist_source(
    repo: InMemorySourceRepository,
    *,
    source_id: str,
    url: str,
    project_id: str,
    run_id: str,
    design_id: str,
    need_id: str,
) -> Source:
    source = Source(
        id=source_id,
        project_id=project_id,
        url=url,
        canonical_url=url,
        title="Existing",
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        retrieval_status=RetrievalStatus.ACQUIRED,
        content_text="existing body",
        query_refs=(f"sq-{need_id}",),
        research_question_refs=("RQ1",),
        information_need_refs=(need_id,),
        workflow_run_refs=(run_id,),
        research_design_refs=(design_id,),
    )
    repo.create(source)
    return source


class DeterministicSourceEligibilityTests(unittest.TestCase):
    def test_case_1_aligned_candidate_outranks_provider_rank1_junk(self) -> None:
        design = _design(
            rq_question=(
                "What buyer requirements apply to premium microgreens suppliers "
                "targeting hotel restaurants?"
            ),
            description=(
                "Capture buyer requirements and procurement criteria "
                "(quality specs, certifications, reliability, MOQs, lead times)."
            ),
            geography="Kenya",
        )
        provider = _ScriptedProvider(
            [
                _candidate(
                    url="https://vendor.example/office-chairs-procurement",
                    title="Office chair procurement checklist MOQ lead times",
                    snippet="B2B chairs procurement configurations and MOQs.",
                    rank=1,
                ),
                _candidate(
                    url="https://produce.example/microgreens-horeca-kenya",
                    title="Premium microgreens buyer requirements for hotel restaurants in Kenya",
                    snippet="Quality specs and certifications for microgreens suppliers.",
                    rank=2,
                ),
            ]
        )
        retriever = _RecordingRetriever()
        service, repo = _service(provider, retriever)
        summary = service.acquire_for_context(_context(design))
        self.assertEqual(provider.calls, 1)
        self.assertEqual(retriever.fetched_urls[0], "https://produce.example/microgreens-horeca-kenya")
        acquired = repo.list_for_project("project-141")
        self.assertTrue(
            any("microgreens-horeca-kenya" in item.canonical_url for item in acquired)
        )
        self.assertGreaterEqual(summary.skipped_ineligible_count, 1)

    def test_case_2_generic_local_need_uses_parent_rq_topic(self) -> None:
        design = _design(
            rq_question=(
                "What procurement criteria do premium microgreens hotel buyers use?"
            ),
            description=(
                "Capture buyer requirements and procurement criteria "
                "(quality specs, certifications, reliability, MOQs, lead times)."
            ),
        )
        context = build_relevance_context(design, design.information_needs[0])
        unrelated = evaluate_candidate(
            context,
            _candidate(
                url="https://industrial.example/steel-bolt-procurement-moq",
                title="Steel bolt procurement MOQ and lead times",
                snippet="Industrial fastener procurement process and certifications.",
                rank=1,
            ),
        )
        aligned = evaluate_candidate(
            context,
            _candidate(
                url="https://fresh.example/microgreens-hotel-buyer-specs",
                title="Microgreens hotel buyer quality specs Kenya",
                snippet="Premium microgreens procurement criteria for hotel kitchens.",
                rank=2,
            ),
        )
        self.assertEqual(unrelated.eligibility, ELIGIBILITY_INELIGIBLE)
        self.assertIn(aligned.eligibility, {ELIGIBILITY_DIRECT, ELIGIBILITY_PROXY})
        self.assertGreater(aligned.tier_rank, unrelated.tier_rank)

    def test_case_3_geography_direct_outranks_proxy_and_unrelated(self) -> None:
        design = _design(
            rq_question="What is the horticulture wholesale capacity in Kenya?",
            description="Estimate horticulture wholesale capacity and supplier density.",
            geography="Kenya",
            expectation=_ee(
                nature=EvidenceNature.MIXED,
                required_aspects=("supplier_density_trend", "capacity_signals"),
                geography="Kenya",
            ),
        )
        context = build_relevance_context(design, design.information_needs[0])
        direct = evaluate_candidate(
            context,
            _candidate(
                url="https://stats.example/kenya-horticulture-wholesale",
                title="Kenya horticulture wholesale capacity 2025",
                snippet="Supplier density for horticulture wholesalers in Kenya.",
                rank=3,
            ),
        )
        proxy = evaluate_candidate(
            context,
            _candidate(
                url="https://global.example/horticulture-wholesale-outlook",
                title="Global horticulture wholesale capacity outlook",
                snippet="Worldwide horticulture supplier density trends.",
                rank=2,
            ),
        )
        unrelated = evaluate_candidate(
            context,
            _candidate(
                url="https://news.example/brazil-horticulture-wholesale",
                title="Brazil horticulture wholesale capacity",
                snippet="Supplier density for horticulture wholesalers in Brazil.",
                rank=1,
            ),
        )
        self.assertEqual(direct.geo_alignment, GEO_DIRECT)
        self.assertEqual(proxy.geo_alignment, GEO_PROXY)
        self.assertEqual(unrelated.geo_alignment, GEO_UNRELATED)
        self.assertGreater(direct.tier_rank, unrelated.tier_rank)
        self.assertGreaterEqual(direct.tier_rank, proxy.tier_rank)
        self.assertNotEqual(proxy.eligibility, ELIGIBILITY_INELIGIBLE)

    def test_case_4_next_candidate_fallback_no_extra_search(self) -> None:
        design = _design(
            rq_question="How do hotel chefs use specialty herbs and microgreens?",
            description="Document chef use-cases, plating applications, and seasonality.",
            geography="Kenya",
        )
        provider = _ScriptedProvider(
            [
                _candidate(
                    url="https://hardware.example/specifications-manual",
                    title="Product specifications manual for industrial sensors",
                    snippet="Electrical specifications and SKU formats.",
                    rank=1,
                ),
                _candidate(
                    url="https://culinary.example/microgreens-chef-use-kenya",
                    title="How hotel chefs use microgreens and specialty herbs in Kenya",
                    snippet="Plating applications and seasonality for microgreens.",
                    rank=2,
                ),
            ]
        )
        retriever = _RecordingRetriever()
        service, _repo = _service(provider, retriever)
        summary = service.acquire_for_context(_context(design))
        self.assertEqual(provider.calls, 1)
        self.assertEqual(retriever.fetched_urls[0], "https://culinary.example/microgreens-chef-use-kenya")
        self.assertEqual(summary.tavily_query_count, 1)

    def test_case_5_fetch_failure_fallback_consumes_attempt_slot(self) -> None:
        design = _design(
            rq_question="What horticulture packaging formats are used in Kenya hotels?",
            description="Map horticulture packaging formats, pack sizes, and shelf life.",
        )
        provider = _ScriptedProvider(
            [
                _candidate(
                    url="https://pack.example/kenya-horticulture-formats",
                    title="Kenya horticulture packaging formats for hotels",
                    snippet="Pack sizes and shelf life for horticulture.",
                    rank=1,
                ),
                _candidate(
                    url="https://pack.example/kenya-horticulture-shelf-life",
                    title="Kenya horticulture shelf life and pack sizes",
                    snippet="Hotel horticulture packaging formats.",
                    rank=2,
                ),
            ]
        )
        retriever = _RecordingRetriever(
            fail_urls=frozenset({"https://pack.example/kenya-horticulture-formats"}),
        )
        service, repo = _service(provider, retriever, max_sources_per_run=2)
        summary = service.acquire_for_context(_context(design))
        self.assertEqual(provider.calls, 1)
        self.assertEqual(len(retriever.fetched_urls), 2)
        self.assertEqual(summary.candidates_attempted, 2)
        self.assertEqual(summary.failed_count, 1)
        self.assertEqual(summary.acquired_count, 1)
        self.assertTrue(
            any("shelf-life" in item.canonical_url for item in repo.list_for_project("project-141"))
        )
        actions = {item.get("action") for item in summary.selection_decisions}
        self.assertIn(ACTION_FETCH_FAILED, actions)

    def test_case_6_provider_rank_tie_breaks_equivalent_eligibility(self) -> None:
        design = _design(
            rq_question="What horticulture supplier lists exist in Kenya?",
            description="Identify horticulture suppliers and their geographic coverage.",
        )
        context = build_relevance_context(design, design.information_needs[0])
        first = evaluate_candidate(
            context,
            _candidate(
                url="https://a.example/kenya-horticulture-suppliers",
                title="Kenya horticulture suppliers list",
                snippet="Geographic coverage of horticulture suppliers in Kenya.",
                rank=1,
            ),
        )
        second = evaluate_candidate(
            context,
            _candidate(
                url="https://b.example/kenya-horticulture-suppliers",
                title="Kenya horticulture suppliers list",
                snippet="Geographic coverage of horticulture suppliers in Kenya.",
                rank=2,
            ),
        )
        self.assertEqual(first.eligibility, second.eligibility)
        self.assertEqual(first.topic_score, second.topic_score)
        self.assertLess(first.provider_rank, second.provider_rank)
        provider = _ScriptedProvider(
            [
                _candidate(
                    url="https://b.example/kenya-horticulture-suppliers",
                    title="Kenya horticulture suppliers list",
                    snippet="Geographic coverage of horticulture suppliers in Kenya.",
                    rank=2,
                ),
                _candidate(
                    url="https://a.example/kenya-horticulture-suppliers",
                    title="Kenya horticulture suppliers list",
                    snippet="Geographic coverage of horticulture suppliers in Kenya.",
                    rank=1,
                ),
            ]
        )
        retriever = _RecordingRetriever()
        service, _repo = _service(provider, retriever)
        service.acquire_for_context(_context(design))
        self.assertEqual(
            retriever.fetched_urls[0],
            "https://a.example/kenya-horticulture-suppliers",
        )

    def test_case_7_exhausted_source_skipped_for_same_need(self) -> None:
        design = _design(
            rq_question="What is the horticulture market size in Kenya?",
            description="Estimate horticulture market size value and recent growth.",
            expectation=_ee(
                nature=EvidenceNature.MIXED,
                required_aspects=("market_value_eur", "growth_rate_cagr"),
                geography="Kenya",
                requires_quantitative_evidence=True,
            ),
        )
        context = _context(design)
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        existing = _persist_source(
            source_repo,
            source_id="source-s",
            url="https://syndicated.example/europe-horticulture-tam",
            project_id=context.project.id,
            run_id=context.workflow_run.id,
            design_id=design.id,
            need_id="IN1",
        )
        context.shared_state["evidence_extraction"] = {
            "diagnostics": {
                "work_items": [
                    {
                        "source_id": existing.id,
                        "information_need_ids": ["IN1"],
                        "extractor_status": "no_candidates",
                    }
                ]
            }
        }
        provider = _ScriptedProvider(
            [
                _candidate(
                    url=existing.url,
                    title="Europe horticulture market size share trends",
                    snippet="Europe horticulture TAM and CAGR.",
                    rank=1,
                ),
                _candidate(
                    url="https://stats.example/kenya-horticulture-market-size",
                    title="Kenya horticulture market size and growth",
                    snippet="Value and CAGR for horticulture in Kenya.",
                    rank=2,
                ),
            ]
        )
        retriever = _RecordingRetriever()
        service, _repo = _service(
            provider,
            retriever,
            source_repo=source_repo,
            evidence_repo=evidence_repo,
        )
        query = SearchQueryBuilder(max_results=3).build_queries(design)[0]
        summary = service.acquire_targeted_queries(context, [query], max_sources=1)
        self.assertEqual(provider.calls, 1)
        self.assertNotIn(existing.url, retriever.fetched_urls)
        self.assertEqual(
            retriever.fetched_urls,
            ["https://stats.example/kenya-horticulture-market-size"],
        )
        self.assertEqual(summary.skipped_exhausted_count, 1)
        actions = {item.get("action") for item in summary.selection_decisions}
        self.assertIn(ACTION_EXHAUSTED, actions)

    def test_case_8_exhaustion_is_need_specific(self) -> None:
        source = Source(
            id="source-s",
            project_id="p",
            url="https://shared.example/page",
            canonical_url="https://shared.example/page",
            title="Shared",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text="body",
        )
        work_items = (
            {
                "source_id": "source-s",
                "information_need_ids": ["IN1"],
                "extractor_status": "no_candidates",
            },
        )
        exhausted = exhausted_canonical_urls_for_need(
            information_need_id="IN1",
            sources=[source],
            evidence_rows=(),
            work_items=work_items,
            workflow_run_id=None,
        )
        not_exhausted_in2 = exhausted_canonical_urls_for_need(
            information_need_id="IN2",
            sources=[source],
            evidence_rows=(),
            work_items=work_items,
            workflow_run_id=None,
        )
        self.assertEqual(exhausted, frozenset({source.canonical_url}))
        self.assertEqual(not_exhausted_in2, frozenset())

    def test_case_9_nonzero_evidence_not_automatically_exhausted(self) -> None:
        source = Source(
            id="source-s",
            project_id="p",
            url="https://shared.example/page",
            canonical_url="https://shared.example/page",
            title="Shared",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text="body",
        )
        evidence = Evidence(
            id="ev-1",
            project_id="p",
            source_id="source-s",
            source_content_checksum="abc",
            workflow_run_id="run-141",
            research_design_id="design-141",
            statement="A grounded horticulture fact.",
            source_excerpt="excerpt",
            created_at=datetime.now(timezone.utc).isoformat(),
            information_need_refs=("IN1",),
        )
        exhausted = exhausted_canonical_urls_for_need(
            information_need_id="IN1",
            sources=[source],
            evidence_rows=(evidence,),
            work_items=(
                {
                    "source_id": "source-s",
                    "information_need_ids": ["IN1"],
                    "extractor_status": "no_candidates",
                },
            ),
            workflow_run_id="run-141",
        )
        self.assertEqual(exhausted, frozenset())

    def test_case_10_no_extra_search_calls(self) -> None:
        design = _design(
            rq_question="What horticulture prices are paid by Kenya hotels?",
            description="Compile horticulture wholesale prices by pack and channel.",
        )
        provider = _ScriptedProvider(
            [
                _candidate(
                    url="https://prices.example/kenya-horticulture-wholesale",
                    title="Kenya horticulture wholesale prices for hotels",
                    snippet="Pack and channel horticulture prices.",
                    rank=1,
                ),
                _candidate(
                    url="https://prices.example/kenya-horticulture-channel",
                    title="Kenya horticulture channel price benchmarks",
                    snippet="Hotel horticulture wholesale prices.",
                    rank=2,
                ),
            ]
        )
        service, _repo = _service(provider, _RecordingRetriever())
        summary = service.acquire_for_context(_context(design))
        self.assertEqual(provider.calls, 1)
        self.assertEqual(summary.tavily_query_count, 1)
        self.assertEqual(summary.queries_executed, 1)

    def test_case_11_source_cap_unchanged(self) -> None:
        design = ResearchDesign(
            id="design-cap",
            research_questions=tuple(
                ResearchQuestion(id=f"RQ{i}", question=f"Question {i}", objective_refs=())
                for i in range(1, 13)
            ),
            information_needs=tuple(
                InformationNeed(
                    id=f"IN{i}",
                    research_question_id=f"RQ{i}",
                    description=f"Need {i}",
                )
                for i in range(1, 13)
            ),
        )

        class _ManyProvider(SearchProvider):
            def __init__(self) -> None:
                self.calls = 0

            def search(self, query: SearchQuery) -> list[SourceCandidate]:
                self.calls += 1
                index = query.information_need_id.replace("IN", "")
                return [
                    _candidate(
                        url=f"https://need-{index}.example/rank-{rank}",
                        title=f"Title {index}-{rank}",
                        snippet="snippet",
                        rank=rank,
                        query_id=query.id,
                    )
                    for rank in range(1, 4)
                ]

        provider = _ManyProvider()
        service, _repo = _service(
            provider,
            _RecordingRetriever(),
            max_sources_per_run=8,
            min_successful=3,
        )
        summary = service.acquire_for_context(_context(design, project_id="project-cap"))
        self.assertEqual(summary.candidate_count_raw, 36)
        self.assertEqual(summary.candidate_count_unique, 36)
        self.assertEqual(summary.candidates_attempted, 8)
        self.assertEqual(summary.skipped_budget_count, 28)
        self.assertEqual(provider.calls, 12)
        budget_src = inspect.getsource(SourceAcquisitionBudget)
        self.assertIn("max_sources_per_run: int = 30", budget_src)

    def test_case_12_legacy_ee_none_searchable(self) -> None:
        design = _design(
            rq_question="Q?",
            description="Need one",
            geography="",
            timeframe="",
            expectation=None,
        )
        provider = _ScriptedProvider(
            [
                _candidate(
                    url="https://example.com/legacy-source",
                    title="Example Market Report",
                    snippet="Market overview snippet.",
                    rank=1,
                )
            ]
        )
        service, repo = _service(provider, _RecordingRetriever())
        summary = service.acquire_for_context(_context(design, project_id="project-legacy"))
        self.assertGreaterEqual(summary.acquired_count, 1)
        self.assertEqual(len(repo.list_for_project("project-legacy")), 1)
        context = build_relevance_context(design, design.information_needs[0])
        self.assertTrue(context.legacy_expectation)
        self.assertEqual(
            evaluate_candidate(
                context,
                _candidate(
                    url="https://example.com/legacy-source",
                    title="Example Market Report",
                    snippet="Market overview snippet.",
                    rank=1,
                ),
            ).eligibility,
            ELIGIBILITY_UNSCORED,
        )

    def test_case_13_live_style_generic_procurement_fixture(self) -> None:
        design = _design(
            rq_question=(
                "What are buyer requirements and procurement criteria impacting "
                "supply of premium microgreens to hotel restaurants?"
            ),
            description=(
                "Capture buyer requirements and procurement criteria "
                "(quality specs, certifications, reliability, MOQs, lead times)."
            ),
            geography="Kenya",
        )
        provider = _ScriptedProvider(
            [
                _candidate(
                    url="https://marketplace.example/home-furnishings-b2b-procurement",
                    title="B2B home furnishings procurement guide 2026",
                    snippet="MOQs, lead times, and quality specs for furnishings buyers.",
                    rank=1,
                ),
                _candidate(
                    url="https://fresh.example/microgreens-hotel-procurement-kenya",
                    title="Premium microgreens procurement criteria for hotel restaurants in Kenya",
                    snippet="Quality specs, certifications, and MOQs for microgreens.",
                    rank=2,
                ),
            ]
        )
        retriever = _RecordingRetriever()
        service, _repo = _service(provider, retriever)
        summary = service.acquire_for_context(_context(design, project_id="project-proc"))
        self.assertNotIn(
            "https://marketplace.example/home-furnishings-b2b-procurement",
            retriever.fetched_urls,
        )
        self.assertEqual(
            retriever.fetched_urls[0],
            "https://fresh.example/microgreens-hotel-procurement-kenya",
        )
        rejected = [
            item
            for item in summary.selection_decisions
            if item.get("action") == ACTION_REJECTED
        ]
        self.assertTrue(rejected)
        src = Path(
            REPO_ROOT,
            "application",
            "sources",
            "deterministic_source_relevance.py",
        ).read_text(encoding="utf-8")
        self.assertNotIn("furniture", src.casefold())
        self.assertNotIn("alibaba", src.casefold())

    def test_case_14_live_style_europe_proxy_fixture(self) -> None:
        design = _design(
            rq_question=(
                "What is the size, growth, and maturity of Kenya's premium "
                "microgreens market for hotel restaurants?"
            ),
            description=(
                "Estimate current market size (value/volume) and recent growth "
                "for premium microgreens in Kenya."
            ),
            geography="Kenya",
            expectation=_ee(
                nature=EvidenceNature.MIXED,
                required_aspects=(
                    "market_value_eur",
                    "market_volume_units",
                    "growth_rate_cagr",
                    "market_maturity_stage",
                ),
                geography="Kenya",
                requires_quantitative_evidence=True,
            ),
        )
        provider = _ScriptedProvider(
            [
                _candidate(
                    url="https://research.example/europe-microgreens-market",
                    title="Europe Microgreens Market Size, Share and Trends, 2034",
                    snippet="European microgreens market value and CAGR outlook.",
                    rank=1,
                ),
                _candidate(
                    url="https://stats.example/kenya-microgreens-market-size",
                    title="Kenya premium microgreens market size and growth",
                    snippet="Value, volume, and CAGR for microgreens in Kenya hotels.",
                    rank=2,
                ),
            ]
        )
        retriever = _RecordingRetriever()
        service, _repo = _service(provider, retriever)
        service.acquire_for_context(_context(design, project_id="project-geo"))
        self.assertEqual(
            retriever.fetched_urls[0],
            "https://stats.example/kenya-microgreens-market-size",
        )
        context = build_relevance_context(design, design.information_needs[0])
        europe = evaluate_candidate(
            context,
            _candidate(
                url="https://research.example/europe-microgreens-market",
                title="Europe Microgreens Market Size, Share and Trends, 2034",
                snippet="European microgreens market value and CAGR outlook.",
                rank=1,
            ),
        )
        self.assertEqual(europe.eligibility, ELIGIBILITY_PROXY)
        self.assertNotEqual(europe.eligibility, ELIGIBILITY_INELIGIBLE)

    def test_case_15_observability_actions(self) -> None:
        design = _design(
            rq_question="What horticulture regulations apply in Kenya?",
            description="Summarize horticulture food safety and labeling rules.",
        )
        provider = _ScriptedProvider(
            [
                _candidate(
                    url="https://unrelated.example/robotics-firmware-spec",
                    title="Robotics firmware specification sheet",
                    snippet="Electrical firmware revision notes.",
                    rank=1,
                ),
                _candidate(
                    url="https://regulator.example/kenya-horticulture-food-safety",
                    title="Kenya horticulture food safety and labeling rules",
                    snippet="Regulatory considerations for horticulture supply.",
                    rank=2,
                ),
            ]
        )
        retriever = _RecordingRetriever()
        service, _repo = _service(provider, retriever, min_successful=1)
        summary = service.acquire_for_context(_context(design, project_id="project-obs"))
        actions = {item.get("action") for item in summary.selection_decisions}
        self.assertIn(ACTION_SELECTED, actions)
        self.assertEqual(
            retriever.fetched_urls[0],
            "https://regulator.example/kenya-horticulture-food-safety",
        )
        self.assertTrue(
            any(item.get("eligibility") == ELIGIBILITY_DIRECT for item in summary.selection_decisions)
            or any(item.get("action") == ACTION_SELECTED for item in summary.selection_decisions)
        )

    def test_tavily_preserves_provider_score_without_config_change(self) -> None:
        client = type("C", (), {})()
        captured = {}

        class _Resp:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "results": [
                        {
                            "url": "https://example.com/a",
                            "title": "A",
                            "content": "Snippet A",
                            "score": 0.91,
                        }
                    ]
                }

        class _Client:
            def post(self, url, json):
                captured["url"] = url
                captured["json"] = json
                return _Resp()

        provider = TavilySearchProvider(api_key="test-key", http_client=_Client())
        query = SearchQuery(
            id="sq-1",
            research_question_id="rq-1",
            information_need_id="in-1",
            query_text="brand awareness",
            max_results=3,
        )
        candidates = provider.search(query)
        self.assertEqual(captured["json"]["query"], "brand awareness")
        self.assertEqual(set(captured["json"]), {"api_key", "query", "max_results"})
        self.assertEqual(candidates[0].metadata.get("provider_score"), "0.91")
        adapter = inspect.getsource(TavilySearchProvider.search)
        tree = ast.parse(inspect.getsource(TavilySearchProvider))
        self.assertTrue(any(isinstance(node, ast.ClassDef) for node in tree.body))
        self.assertNotIn("search_depth", adapter)
        self.assertNotIn("include_domains", adapter)


def _insect_design() -> ResearchDesign:
    return _design(
        rq_question=(
            "What is the farmed insect protein feed market outlook in Kenya?"
        ),
        description=(
            "Capture buyer requirements and procurement criteria "
            "(quality specs, certifications, reliability, MOQs, lead times)."
        ),
        geography="Kenya",
    )


class AdversarialRelevanceAndExhaustionGateTests(unittest.TestCase):
    def test_case_a1_synonym_without_lexical_overlap_is_not_hard_rejected(self) -> None:
        design = _insect_design()
        context = build_relevance_context(design, design.information_needs[0])
        synonym = evaluate_candidate(
            context,
            _candidate(
                url="https://trade.example/cricket-meal-poultry-rations",
                title="Commercial cricket meal demand for poultry rations",
                snippet="Trade notes on cricket meal inclusion in poultry rations.",
                rank=1,
            ),
        )
        self.assertEqual(synonym.eligibility, ELIGIBILITY_UNSCORED)
        self.assertTrue(synonym.is_fetch_eligible)
        self.assertEqual(synonym.reason, "no_positive_topic_signal_unscored")
        self.assertEqual(synonym.topic_score, 0)

    def test_case_a2_generic_official_title_remains_fetchable(self) -> None:
        design = _insect_design()
        context = build_relevance_context(design, design.information_needs[0])
        official = evaluate_candidate(
            context,
            _candidate(
                url="https://stats.example/yearbook-2024",
                title="National Statistical Yearbook 2024",
                snippet="Official compilation of economic accounts by the statistics office.",
                rank=1,
            ),
        )
        self.assertEqual(official.eligibility, ELIGIBILITY_UNSCORED)
        self.assertTrue(official.is_fetch_eligible)
        self.assertNotEqual(official.eligibility, ELIGIBILITY_INELIGIBLE)

    def test_case_a3_generic_contract_mismatch_remains_rejectable(self) -> None:
        design = _insect_design()
        context = build_relevance_context(design, design.information_needs[0])
        unrelated = evaluate_candidate(
            context,
            _candidate(
                url="https://vendor.example/office-chairs-procurement",
                title="Office chair procurement checklist MOQ lead times",
                snippet="B2B chairs procurement configurations and MOQs.",
                rank=1,
            ),
        )
        self.assertEqual(unrelated.eligibility, ELIGIBILITY_INELIGIBLE)
        self.assertEqual(unrelated.reason, "generic_local_overlap_without_parent_topic")

    def test_case_a4_absence_is_not_positive_unrelatedness(self) -> None:
        design = _insect_design()
        context = build_relevance_context(design, design.information_needs[0])
        absent = evaluate_candidate(
            context,
            _candidate(
                url="https://stats.example/yearbook-2024",
                title="National Statistical Yearbook 2024",
                snippet="Official compilation of economic accounts.",
                rank=2,
            ),
        )
        conflicting = evaluate_candidate(
            context,
            _candidate(
                url="https://vendor.example/office-chairs-procurement",
                title="Office chair procurement checklist MOQ lead times",
                snippet="B2B chairs procurement configurations and MOQs.",
                rank=1,
            ),
        )
        self.assertEqual(absent.reason, "no_positive_topic_signal_unscored")
        self.assertTrue(absent.is_fetch_eligible)
        self.assertEqual(conflicting.reason, "generic_local_overlap_without_parent_topic")
        self.assertFalse(conflicting.is_fetch_eligible)
        self.assertNotEqual(absent.eligibility, conflicting.eligibility)

    def test_case_a5_weak_proxy_alignment_remains_eligible(self) -> None:
        design = _insect_design()
        context = build_relevance_context(design, design.information_needs[0])
        proxy = evaluate_candidate(
            context,
            _candidate(
                url="https://global.example/insect-protein-feed-outlook",
                title="Global insect protein feed outlook for livestock rations",
                snippet="Worldwide insect protein feed demand for livestock.",
                rank=1,
            ),
        )
        self.assertEqual(proxy.eligibility, ELIGIBILITY_PROXY)
        self.assertTrue(proxy.is_fetch_eligible)

    def test_case_a6_aligned_still_outranks_rank1_junk(self) -> None:
        design = _insect_design()
        provider = _ScriptedProvider(
            [
                _candidate(
                    url="https://vendor.example/office-chairs-procurement",
                    title="Office chair procurement checklist MOQ lead times",
                    snippet="B2B chairs procurement configurations and MOQs.",
                    rank=1,
                ),
                _candidate(
                    url="https://agri.example/kenya-insect-protein-feed",
                    title="Kenya farmed insect protein feed market outlook",
                    snippet="Insect protein feed supply for livestock rations in Kenya.",
                    rank=2,
                ),
            ]
        )
        retriever = _RecordingRetriever()
        service, _repo = _service(provider, retriever)
        service.acquire_for_context(_context(design, project_id="project-a6"))
        self.assertEqual(provider.calls, 1)
        self.assertEqual(
            retriever.fetched_urls[0],
            "https://agri.example/kenya-insect-protein-feed",
        )

    def test_case_b1_valid_empty_extraction_may_exhaust(self) -> None:
        source = Source(
            id="source-s",
            project_id="p",
            url="https://shared.example/page",
            canonical_url="https://shared.example/page",
            title="Shared",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text="body",
        )
        work_item = {
            "source_id": "source-s",
            "information_need_ids": ["IN1"],
            "extractor_status": "no_candidates",
            "inner_chunks": [
                {
                    "extractor_status": "success",
                    "raw_candidate_count": 0,
                    "response_shape": {"response_classification": "valid_empty_result"},
                }
            ],
        }
        self.assertTrue(work_item_is_valid_zero_yield(work_item))
        exhausted = exhausted_canonical_urls_for_need(
            information_need_id="IN1",
            sources=[source],
            evidence_rows=(),
            work_items=(work_item,),
        )
        self.assertEqual(exhausted, frozenset({source.canonical_url}))

    def test_case_b2_invalid_json_is_not_semantically_exhausted(self) -> None:
        source = Source(
            id="source-s",
            project_id="p",
            url="https://shared.example/page",
            canonical_url="https://shared.example/page",
            title="Shared",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text="body",
        )
        work_item = {
            "source_id": "source-s",
            "information_need_ids": ["IN1"],
            "extractor_status": "no_candidates",
            "inner_chunks": [
                {
                    "extractor_status": "exception",
                    "exception_class": "EvidenceResponseOutcomeError",
                    "response_shape": {"response_classification": "invalid_json"},
                }
            ],
        }
        self.assertFalse(work_item_is_valid_zero_yield(work_item))
        exhausted = exhausted_canonical_urls_for_need(
            information_need_id="IN1",
            sources=[source],
            evidence_rows=(),
            work_items=(work_item,),
        )
        self.assertEqual(exhausted, frozenset())

    def test_case_b3_provider_failure_is_not_exhausted(self) -> None:
        source = Source(
            id="source-s",
            project_id="p",
            url="https://shared.example/page",
            canonical_url="https://shared.example/page",
            title="Shared",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text="body",
        )
        work_item = {
            "source_id": "source-s",
            "information_need_ids": ["IN1"],
            "extractor_status": "exception",
            "exception_class": "TimeoutError",
            "exception_message": "provider timeout",
        }
        self.assertFalse(work_item_is_valid_zero_yield(work_item))
        exhausted = exhausted_canonical_urls_for_need(
            information_need_id="IN1",
            sources=[source],
            evidence_rows=(),
            work_items=(work_item,),
        )
        self.assertEqual(exhausted, frozenset())

    def test_case_b4_grounding_rejection_is_not_source_exhaustion(self) -> None:
        source = Source(
            id="source-s",
            project_id="p",
            url="https://shared.example/page",
            canonical_url="https://shared.example/page",
            title="Shared",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text="body",
        )
        work_item = {
            "source_id": "source-s",
            "information_need_ids": ["IN1"],
            "extractor_status": "success",
            "raw_candidate_count": 2,
            "candidate_outcomes": [
                {"outcome": "rejected", "rejection_reason": "grounding"},
                {"outcome": "rejected", "rejection_reason": "grounding"},
            ],
        }
        self.assertFalse(work_item_is_valid_zero_yield(work_item))
        exhausted = exhausted_canonical_urls_for_need(
            information_need_id="IN1",
            sources=[source],
            evidence_rows=(),
            work_items=(work_item,),
        )
        self.assertEqual(exhausted, frozenset())

    def test_case_b5_nonzero_evidence_not_exhausted(self) -> None:
        source = Source(
            id="source-s",
            project_id="p",
            url="https://shared.example/page",
            canonical_url="https://shared.example/page",
            title="Shared",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text="body",
        )
        evidence = Evidence(
            id="ev-1",
            project_id="p",
            source_id="source-s",
            source_content_checksum="abc",
            workflow_run_id="run-141",
            research_design_id="design-141",
            statement="A grounded insect protein fact.",
            source_excerpt="excerpt",
            created_at=datetime.now(timezone.utc).isoformat(),
            information_need_refs=("IN1",),
        )
        exhausted = exhausted_canonical_urls_for_need(
            information_need_id="IN1",
            sources=[source],
            evidence_rows=(evidence,),
            work_items=(
                {
                    "source_id": "source-s",
                    "information_need_ids": ["IN1"],
                    "extractor_status": "success",
                    "raw_candidate_count": 1,
                    "candidate_outcomes": [{"outcome": "persisted"}],
                },
            ),
            workflow_run_id="run-141",
        )
        self.assertEqual(exhausted, frozenset())

    def test_case_b6_exhaustion_remains_need_specific(self) -> None:
        source = Source(
            id="source-s",
            project_id="p",
            url="https://shared.example/page",
            canonical_url="https://shared.example/page",
            title="Shared",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text="body",
        )
        work_items = (
            {
                "source_id": "source-s",
                "information_need_ids": ["IN1"],
                "extractor_status": "no_candidates",
            },
        )
        self.assertEqual(
            exhausted_canonical_urls_for_need(
                information_need_id="IN1",
                sources=[source],
                evidence_rows=(),
                work_items=work_items,
            ),
            frozenset({source.canonical_url}),
        )
        self.assertEqual(
            exhausted_canonical_urls_for_need(
                information_need_id="IN2",
                sources=[source],
                evidence_rows=(),
                work_items=work_items,
            ),
            frozenset(),
        )


if __name__ == "__main__":
    unittest.main()

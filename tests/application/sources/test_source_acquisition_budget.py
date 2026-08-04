"""Deterministic live-shape regression tests for source acquisition budgets."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.project import Project
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.search_query import SearchQuery
from domain.sources.source import Source
from domain.sources.source_candidate import SourceCandidate
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template import WorkflowTemplate

from application.executors.search_executor import SearchExecutor
from application.ports.source_ports import SearchProvider, SourceRetriever
from application.sources.exceptions import SourceAcquisitionError
from application.sources.search_query_builder import SearchQueryBuilder
from application.sources.source_acquisition_service import SourceAcquisitionService
from application.sources.source_budget import SourceAcquisitionBudget
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)
from runtime.workflow_context import WorkflowContext


def _design_with_needs(count: int, *, design_id: str = "design-live") -> ResearchDesign:
    questions = tuple(
        ResearchQuestion(id=f"rq-{index}", question=f"Question {index}", objective_refs=())
        for index in range(1, count + 1)
    )
    needs = tuple(
        InformationNeed(
            id=f"in-{index}",
            research_question_id=f"rq-{index}",
            description=f"Need {index}",
        )
        for index in range(1, count + 1)
    )
    return ResearchDesign(
        id=design_id,
        research_questions=questions,
        information_needs=needs,
    )


def _workflow_context(design: ResearchDesign, *, project_id: str = "project-live") -> WorkflowContext:
    template = WorkflowTemplate(
        id="template-live",
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
    run.id = "run-live-shape"
    context = WorkflowContext(
        project=Project(id=project_id, name="Project"),
        workflow_template=template,
        workflow_run=run,
    )
    context.current_task = run.tasks[0]
    return context


class _UniversalCoverageSearchProvider(SearchProvider):
    """Same rank-1 URL in every query; one fetch merges coverage for all needs."""

    def search(self, query: SearchQuery) -> list[SourceCandidate]:
        need_index = int(query.information_need_id.rsplit("-", 1)[-1])
        candidates = [
            SourceCandidate(
                provider="deterministic",
                url="https://shared.example/universal-coverage",
                title="Universal",
                snippet="covers all",
                query_id=query.id,
                rank=1,
            ),
        ]
        for rank in range(2, 6):
            candidates.append(
                SourceCandidate(
                    provider="deterministic",
                    url=f"https://need-{need_index}.example/rank-{rank}",
                    title=f"Extra {need_index}-{rank}",
                    snippet="extra",
                    query_id=query.id,
                    rank=rank,
                ),
            )
        return candidates


class _SplitCoverageSearchProvider(SearchProvider):
    """Each need's primary URL covers only that need."""

    def search(self, query: SearchQuery) -> list[SourceCandidate]:
        need_index = int(query.information_need_id.rsplit("-", 1)[-1])
        return [
            SourceCandidate(
                provider="deterministic",
                url=f"https://coverage-{need_index}.example/primary",
                title=f"Primary {need_index}",
                snippet="primary",
                query_id=query.id,
                rank=1,
            ),
            SourceCandidate(
                provider="deterministic",
                url=f"https://extra-{need_index}.example/backup",
                title=f"Backup {need_index}",
                snippet="backup",
                query_id=query.id,
                rank=2,
            ),
        ]


class _DistinctNeedSearchProvider(SearchProvider):
    """Returns unique rank-1 URLs per information need (no cross-query sharing)."""

    def search(self, query: SearchQuery) -> list[SourceCandidate]:
        need_index = int(query.information_need_id.rsplit("-", 1)[-1])
        return [
            SourceCandidate(
                provider="deterministic",
                url=f"https://need-{need_index}.example/rank-{rank}",
                title=f"Title {need_index}-{rank}",
                snippet="snippet",
                query_id=query.id,
                rank=rank,
            )
            for rank in range(1, 6)
        ]


class _RankedSearchProvider(SearchProvider):
    """Returns five ranked URLs per query with controlled duplicates."""

    def search(self, query: SearchQuery) -> list[SourceCandidate]:
        need_index = int(query.information_need_id.rsplit("-", 1)[-1])
        candidates: list[SourceCandidate] = []
        for rank in range(1, 6):
            if rank == 1 and need_index > 1:
                url = "https://shared.example/top-result"
            else:
                url = f"https://need-{need_index}.example/rank-{rank}"
            candidates.append(
                SourceCandidate(
                    provider="deterministic",
                    url=url,
                    title=f"Title {need_index}-{rank}",
                    snippet="snippet",
                    query_id=query.id,
                    rank=rank,
                ),
            )
        return candidates


class _TrackingRetriever(SourceRetriever):
    def __init__(
        self,
        *,
        fail_urls: frozenset[str] = frozenset(),
        delay_urls: frozenset[str] = frozenset(),
    ) -> None:
        self.fetched_urls: list[str] = []
        self.fetch_count = 0
        self._fail_urls = fail_urls
        self._delay_urls = delay_urls

    def retrieve(self, candidate: SourceCandidate) -> Source:
        now = datetime.now(timezone.utc).isoformat()
        self.fetch_count += 1
        self.fetched_urls.append(candidate.url)
        if candidate.url in self._delay_urls:
            pass
        if candidate.url in self._fail_urls:
            return Source(
                id="",
                project_id="",
                url=candidate.url,
                canonical_url=candidate.url,
                title=candidate.title,
                retrieved_at=now,
                retrieval_status=RetrievalStatus.FAILED,
                metadata={"reason": "test failure", "failure_category": "timeout"},
            )
        return Source(
            id="",
            project_id="",
            url=candidate.url,
            canonical_url=candidate.url,
            title=candidate.title,
            retrieved_at=now,
            content_type="text/html",
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text=f"Body for {candidate.url}",
        )


class _AllFailedRetriever(SourceRetriever):
    def retrieve(self, candidate: SourceCandidate) -> Source:
        now = datetime.now(timezone.utc).isoformat()
        return Source(
            id="",
            project_id="",
            url=candidate.url,
            canonical_url=candidate.url,
            title=candidate.title,
            retrieved_at=now,
            retrieval_status=RetrievalStatus.FAILED,
            metadata={"reason": "always fails", "failure_category": "http_error"},
        )


class SourceAcquisitionBudgetTests(unittest.TestCase):
    def test_scenario_a_unique_cap_priority_dedup_and_provenance(self) -> None:
        design = _design_with_needs(10)
        context = _workflow_context(design)
        repository = InMemorySourceRepository()
        retriever = _TrackingRetriever()
        budget = SourceAcquisitionBudget(
            max_candidates_per_query=5,
            max_candidates_per_information_need=5,
            max_sources_per_run=8,
            min_successful_sources=3,
            acquisition_max_seconds=300.0,
        )
        service = SourceAcquisitionService(
            search_provider=_DistinctNeedSearchProvider(),
            source_retriever=retriever,
            source_repository=repository,
            query_builder=SearchQueryBuilder(max_results=5),
            budget=budget,
        )

        summary = service.acquire_for_context(context)

        self.assertEqual(summary.candidate_count_raw, 50)
        self.assertEqual(summary.candidate_count_unique, 50)
        self.assertEqual(summary.candidates_attempted, 8)
        self.assertEqual(summary.skipped_budget_count, 42)
        self.assertEqual(retriever.fetch_count, 8)
        self.assertEqual(len(set(retriever.fetched_urls)), 8)
        self.assertEqual(retriever.fetched_urls[0], "https://need-1.example/rank-1")
        self.assertGreaterEqual(summary.acquired_count, 3)

        first_source = repository.get_by_canonical_url_for_project(
            "project-live",
            "https://need-1.example/rank-1",
        )
        self.assertIsNotNone(first_source)
        assert first_source is not None
        self.assertIn("sq-in-1", first_source.query_refs)
        self.assertIn("in-1", first_source.information_need_refs)

    def test_scenario_b_failures_with_enough_success_before_budget(self) -> None:
        design = _design_with_needs(4)
        context = _workflow_context(design, project_id="project-b")
        retriever = _TrackingRetriever(
            fail_urls=frozenset(
                {
                    "https://need-4.example/rank-1",
                },
            ),
        )
        service = SourceAcquisitionService(
            search_provider=_DistinctNeedSearchProvider(),
            source_retriever=retriever,
            source_repository=InMemorySourceRepository(),
            query_builder=SearchQueryBuilder(max_results=5),
            budget=SourceAcquisitionBudget(
                max_sources_per_run=10,
                min_successful_sources=3,
                min_information_need_coverage_ratio=0.75,
                acquisition_max_seconds=120.0,
            ),
        )

        summary = service.acquire_for_context(context)
        executor = SearchExecutor(source_acquisition_service=service)
        executor.run(context)

        self.assertGreaterEqual(summary.acquired_count, 3)
        self.assertGreater(summary.failed_count, 0)
        self.assertFalse(summary.budget_exhausted)
        self.assertIn("source_acquisition", context.shared_state)

    def test_scenario_c_budget_exhaustion_stops_further_fetches(self) -> None:
        design = _design_with_needs(6)
        context = _workflow_context(design, project_id="project-c")
        repository = InMemorySourceRepository()
        retriever = _TrackingRetriever()
        budget = SourceAcquisitionBudget(
            max_sources_per_run=20,
            min_successful_sources=2,
            min_information_need_coverage_ratio=1.0,
            acquisition_max_seconds=1.0,
        )
        service = SourceAcquisitionService(
            search_provider=_DistinctNeedSearchProvider(),
            source_retriever=retriever,
            source_repository=repository,
            query_builder=SearchQueryBuilder(max_results=5),
            budget=budget,
        )

        with patch(
            "application.sources.source_acquisition_service.time.monotonic",
            side_effect=[0.0, 0.0, 0.4, 0.4, 1.2, 1.2, 1.2, 1.2],
        ):
            summary = service.acquire_for_context(context)

        self.assertTrue(summary.budget_exhausted)
        self.assertEqual(retriever.fetch_count, 3)
        self.assertGreaterEqual(summary.acquired_count, 2)
        self.assertGreater(summary.skipped_budget_count, 0)
        persisted = repository.list_for_project("project-c")
        self.assertGreaterEqual(len(persisted), 2)

    def test_scenario_d_zero_acquired_raises(self) -> None:
        design = ResearchDesign(
            id="design-zero",
            research_questions=(
                ResearchQuestion(id="rq-1", question="Q1", objective_refs=()),
            ),
            information_needs=(
                InformationNeed(
                    id="in-1",
                    research_question_id="rq-1",
                    description="Need one",
                ),
            ),
        )
        context = _workflow_context(design, project_id="project-zero")
        service = SourceAcquisitionService(
            search_provider=_RankedSearchProvider(),
            source_retriever=_AllFailedRetriever(),
            source_repository=InMemorySourceRepository(),
            query_builder=SearchQueryBuilder(max_results=5),
            budget=SourceAcquisitionBudget(min_successful_sources=1),
        )

        with self.assertRaises(SourceAcquisitionError):
            service.acquire_for_context(context)

    def test_scenario_e_minimum_threshold_allows_partial_candidate_set(self) -> None:
        design = _design_with_needs(6)
        context = _workflow_context(design, project_id="project-e")
        service = SourceAcquisitionService(
            search_provider=_DistinctNeedSearchProvider(),
            source_retriever=_TrackingRetriever(),
            source_repository=InMemorySourceRepository(),
            query_builder=SearchQueryBuilder(max_results=5),
            budget=SourceAcquisitionBudget(
                max_sources_per_run=4,
                min_successful_sources=3,
                min_information_need_coverage_ratio=1.0,
                acquisition_max_seconds=300.0,
            ),
        )

        summary = service.acquire_for_context(context)

        self.assertGreaterEqual(summary.acquired_count, 3)
        self.assertEqual(summary.candidates_attempted, 4)
        self.assertFalse(summary.coverage_target_satisfied)
        self.assertGreater(summary.skipped_budget_count, 0)
        self.assertTrue(
            any("coverage incomplete" in item for item in summary.limitations),
        )


class SourceAcquisitionCoveragePolicyTests(unittest.TestCase):
    def test_min_success_floor_does_not_stop_after_three_sources(self) -> None:
        design = _design_with_needs(6)
        context = _workflow_context(design, project_id="project-min-floor")
        retriever = _TrackingRetriever()
        service = SourceAcquisitionService(
            search_provider=_DistinctNeedSearchProvider(),
            source_retriever=retriever,
            source_repository=InMemorySourceRepository(),
            query_builder=SearchQueryBuilder(max_results=5),
            budget=SourceAcquisitionBudget(
                max_sources_per_run=30,
                min_successful_sources=3,
                min_information_need_coverage_ratio=1.0,
            ),
        )

        summary = service.acquire_for_context(context)

        self.assertGreater(retriever.fetch_count, 3)
        self.assertGreaterEqual(summary.acquired_count, 3)
        self.assertTrue(summary.coverage_target_satisfied)
        self.assertTrue(summary.coverage_complete_early_stop)

    def test_acquisition_continues_until_information_needs_are_covered(self) -> None:
        design = _design_with_needs(5)
        context = _workflow_context(design, project_id="project-need-cover")
        retriever = _TrackingRetriever()
        service = SourceAcquisitionService(
            search_provider=_DistinctNeedSearchProvider(),
            source_retriever=retriever,
            source_repository=InMemorySourceRepository(),
            query_builder=SearchQueryBuilder(max_results=5),
            budget=SourceAcquisitionBudget(
                max_sources_per_run=30,
                min_successful_sources=1,
                min_information_need_coverage_ratio=1.0,
            ),
        )

        summary = service.acquire_for_context(context)

        self.assertEqual(summary.information_needs_covered_count, 5)
        self.assertEqual(summary.information_needs_total, 5)
        self.assertEqual(retriever.fetch_count, 5)

    def test_coverage_complete_stops_before_max_sources_per_run(self) -> None:
        design = _design_with_needs(3)
        context = _workflow_context(design, project_id="project-cover-early")
        retriever = _TrackingRetriever()
        service = SourceAcquisitionService(
            search_provider=_DistinctNeedSearchProvider(),
            source_retriever=retriever,
            source_repository=InMemorySourceRepository(),
            query_builder=SearchQueryBuilder(max_results=5),
            budget=SourceAcquisitionBudget(
                max_sources_per_run=30,
                min_successful_sources=1,
                min_information_need_coverage_ratio=1.0,
            ),
        )

        summary = service.acquire_for_context(context)

        self.assertTrue(summary.coverage_complete_early_stop)
        self.assertEqual(retriever.fetch_count, 3)
        self.assertLess(retriever.fetch_count, 30)
        self.assertGreater(summary.skipped_budget_count, 0)

    def test_budget_exhaustion_with_minimum_sources_succeeds_with_limitation(self) -> None:
        design = _design_with_needs(6)
        context = _workflow_context(design, project_id="project-budget-limit")
        service = SourceAcquisitionService(
            search_provider=_DistinctNeedSearchProvider(),
            source_retriever=_TrackingRetriever(),
            source_repository=InMemorySourceRepository(),
            query_builder=SearchQueryBuilder(max_results=5),
            budget=SourceAcquisitionBudget(
                max_sources_per_run=20,
                min_successful_sources=2,
                min_information_need_coverage_ratio=1.0,
                acquisition_max_seconds=1.0,
            ),
        )

        with patch(
            "application.sources.source_acquisition_service.time.monotonic",
            side_effect=[0.0, 0.0, 0.4, 0.4, 1.2, 1.2, 1.2, 1.2],
        ):
            summary = service.acquire_for_context(context)

        self.assertTrue(summary.budget_exhausted)
        self.assertGreaterEqual(summary.acquired_count, 2)
        self.assertFalse(summary.coverage_target_satisfied)
        self.assertTrue(
            any("coverage incomplete" in item for item in summary.limitations),
        )

    def test_below_minimum_successful_sources_still_fails(self) -> None:
        design = _design_with_needs(4)
        context = _workflow_context(design, project_id="project-below-min")
        service = SourceAcquisitionService(
            search_provider=_DistinctNeedSearchProvider(),
            source_retriever=_TrackingRetriever(
                fail_urls=frozenset(
                    {
                        "https://need-3.example/rank-1",
                        "https://need-4.example/rank-1",
                    },
                ),
            ),
            source_repository=InMemorySourceRepository(),
            query_builder=SearchQueryBuilder(max_results=5),
            budget=SourceAcquisitionBudget(
                max_sources_per_run=10,
                min_successful_sources=3,
                min_information_need_coverage_ratio=1.0,
                acquisition_max_seconds=1.0,
            ),
        )

        with patch(
            "application.sources.source_acquisition_service.time.monotonic",
            side_effect=[0.0, 0.0, 0.2, 0.2, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5],
        ):
            with self.assertRaises(SourceAcquisitionError):
                service.acquire_for_context(context)


class SourceAcquisitionMinimumCoverageGateTests(unittest.TestCase):
    def test_a_one_source_covering_all_needs_does_not_early_stop_at_minimum_three(self) -> None:
        design = _design_with_needs(3)
        context = _workflow_context(design, project_id="project-gate-a")
        retriever = _TrackingRetriever()
        service = SourceAcquisitionService(
            search_provider=_UniversalCoverageSearchProvider(),
            source_retriever=retriever,
            source_repository=InMemorySourceRepository(),
            query_builder=SearchQueryBuilder(max_results=5),
            budget=SourceAcquisitionBudget(
                max_sources_per_run=30,
                min_successful_sources=3,
                min_information_need_coverage_ratio=1.0,
            ),
        )

        summary = service.acquire_for_context(context)

        self.assertEqual(retriever.fetch_count, 3)
        self.assertTrue(summary.coverage_target_satisfied)
        self.assertTrue(summary.coverage_complete_early_stop)
        self.assertEqual(summary.acquired_count, 3)

    def test_b_two_sources_covering_all_needs_do_not_early_stop(self) -> None:
        design = _design_with_needs(2)
        context = _workflow_context(design, project_id="project-gate-b")
        retriever = _TrackingRetriever()
        service = SourceAcquisitionService(
            search_provider=_SplitCoverageSearchProvider(),
            source_retriever=retriever,
            source_repository=InMemorySourceRepository(),
            query_builder=SearchQueryBuilder(max_results=5),
            budget=SourceAcquisitionBudget(
                max_sources_per_run=30,
                min_successful_sources=3,
                min_information_need_coverage_ratio=1.0,
            ),
        )

        summary = service.acquire_for_context(context)

        self.assertEqual(retriever.fetch_count, 3)
        self.assertTrue(summary.coverage_target_satisfied)
        self.assertTrue(summary.coverage_complete_early_stop)

    def test_c_third_successful_source_with_full_coverage_allows_early_stop(self) -> None:
        design = _design_with_needs(2)
        context = _workflow_context(design, project_id="project-gate-c")
        retriever = _TrackingRetriever()
        service = SourceAcquisitionService(
            search_provider=_SplitCoverageSearchProvider(),
            source_retriever=retriever,
            source_repository=InMemorySourceRepository(),
            query_builder=SearchQueryBuilder(max_results=5),
            budget=SourceAcquisitionBudget(
                max_sources_per_run=30,
                min_successful_sources=3,
                min_information_need_coverage_ratio=1.0,
            ),
        )

        summary = service.acquire_for_context(context)

        self.assertEqual(retriever.fetch_count, 3)
        self.assertEqual(summary.acquired_count, 3)
        self.assertTrue(summary.coverage_target_satisfied)
        self.assertTrue(summary.coverage_complete_early_stop)
        self.assertGreater(summary.skipped_budget_count, 0)

    def test_d_exhausted_budget_with_two_sources_fails_at_full_coverage(self) -> None:
        design = _design_with_needs(2)
        context = _workflow_context(design, project_id="project-gate-d")
        service = SourceAcquisitionService(
            search_provider=_SplitCoverageSearchProvider(),
            source_retriever=_TrackingRetriever(),
            source_repository=InMemorySourceRepository(),
            query_builder=SearchQueryBuilder(max_results=5),
            budget=SourceAcquisitionBudget(
                max_sources_per_run=20,
                min_successful_sources=3,
                min_information_need_coverage_ratio=1.0,
                acquisition_max_seconds=1.0,
            ),
        )

        with patch(
            "application.sources.source_acquisition_service.time.monotonic",
            side_effect=[0.0, 0.0, 0.3, 1.2, 1.2, 1.2],
        ):
            with self.assertRaises(SourceAcquisitionError):
                service.acquire_for_context(context)

    def test_e_exhausted_budget_with_three_sources_and_incomplete_coverage_succeeds(
        self,
    ) -> None:
        design = _design_with_needs(6)
        context = _workflow_context(design, project_id="project-gate-e")
        service = SourceAcquisitionService(
            search_provider=_DistinctNeedSearchProvider(),
            source_retriever=_TrackingRetriever(),
            source_repository=InMemorySourceRepository(),
            query_builder=SearchQueryBuilder(max_results=5),
            budget=SourceAcquisitionBudget(
                max_sources_per_run=20,
                min_successful_sources=3,
                min_information_need_coverage_ratio=1.0,
                acquisition_max_seconds=1.0,
            ),
        )

        with patch(
            "application.sources.source_acquisition_service.time.monotonic",
            side_effect=[0.0, 0.0, 0.3, 0.3, 0.6, 0.6, 1.2, 1.2, 1.2, 1.2],
        ):
            summary = service.acquire_for_context(context)

        self.assertTrue(summary.budget_exhausted)
        self.assertGreaterEqual(summary.acquired_count, 3)
        self.assertFalse(summary.coverage_target_satisfied)
        self.assertFalse(summary.coverage_complete_early_stop)
        self.assertTrue(
            any("coverage incomplete" in item for item in summary.limitations),
        )


if __name__ == "__main__":
    unittest.main()

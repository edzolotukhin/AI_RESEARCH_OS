from __future__ import annotations

import unittest
from datetime import datetime, timezone

from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.sources.retrieval_status import RetrievalStatus

from application.executors.search_executor import SearchExecutor
from application.ports.source_ports import SourceRetriever
from application.sources.exceptions import SourceAcquisitionError
from application.sources.provenance_merge import is_successful_acquisition
from application.sources.search_query_builder import SearchQueryBuilder
from application.sources.source_acquisition_service import SourceAcquisitionService
from domain.sources.search_query import SearchQuery
from domain.sources.source_candidate import SourceCandidate
from domain.sources.source import Source
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)
from infrastructure.search.deterministic_search_adapter import (
    DeterministicSearchProvider,
    DeterministicSourceRetriever,
)
from runtime.workflow_context import WorkflowContext
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.factories.task_factory import TaskFactory
from domain.project import Project
from domain.workflow_template import WorkflowTemplate
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType


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
            metadata={"reason": "test retrieval failure"},
        )


class _DuplicateQueryProvider(DeterministicSearchProvider):
    def search(self, query: SearchQuery) -> list[SourceCandidate]:
        base = super().search(query)
        if query.information_need_id == "in-duplicate":
            base.append(
                SourceCandidate(
                    provider="deterministic",
                    url="https://example.com/market-report?utm_source=test",
                    title="Duplicate",
                    snippet="dup",
                    query_id=query.id,
                    rank=99,
                ),
            )
        return base


class SourceAcquisitionServiceTests(unittest.TestCase):
    def test_deduplicates_same_canonical_url_across_queries(self) -> None:
        design = ResearchDesign(
            id="design-dedup",
            research_questions=(
                ResearchQuestion(id="rq-1", question="Q1", objective_refs=()),
                ResearchQuestion(id="rq-2", question="Q2", objective_refs=()),
            ),
            information_needs=(
                InformationNeed(
                    id="in-1",
                    research_question_id="rq-1",
                    description="Need one",
                ),
                InformationNeed(
                    id="in-duplicate",
                    research_question_id="rq-2",
                    description="Need duplicate",
                ),
            ),
        )
        template = WorkflowTemplate(
            id="template-1",
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
        run.id = "run-dedup-test"
        context = WorkflowContext(
            project=Project(id="project-1", name="Project"),
            workflow_template=template,
            workflow_run=run,
        )
        context.current_task = run.tasks[0]

        repository = InMemorySourceRepository()
        service = SourceAcquisitionService(
            search_provider=_DuplicateQueryProvider(),
            source_retriever=DeterministicSourceRetriever(),
            source_repository=repository,
            query_builder=SearchQueryBuilder(),
        )
        summary = service.acquire_for_context(context)
        sources = repository.list_for_project("project-1")
        acquired = [
            source
            for source in sources
            if source.retrieval_status == RetrievalStatus.ACQUIRED
        ]
        self.assertGreaterEqual(len(acquired), 1)
        canonical_urls = {source.canonical_url for source in sources}
        self.assertEqual(
            len(canonical_urls),
            len(sources),
            "Each persisted source should have a unique canonical URL",
        )
        merged = next(
            source
            for source in sources
            if "example.com/market-report" in source.canonical_url
        )
        self.assertIn("sq-in-1", merged.query_refs)
        self.assertIn("sq-in-duplicate", merged.query_refs)
        self.assertIn(run.id, merged.workflow_run_refs)
        self.assertGreaterEqual(summary.sources_acquired, 1)

    def test_later_content_change_does_not_overwrite_acquired_snapshot(self) -> None:
        design = ResearchDesign(
            id="design-immutable",
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
        template = WorkflowTemplate(
            id="template-immutable",
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
        repository = InMemorySourceRepository()
        service = SourceAcquisitionService(
            search_provider=DeterministicSearchProvider(),
            source_retriever=DeterministicSourceRetriever(),
            source_repository=repository,
            query_builder=SearchQueryBuilder(),
        )

        run_a = WorkflowRunFactory(task_factory=TaskFactory()).create(
            template=template,
            run_id="run-a",
        )
        context_a = WorkflowContext(
            project=Project(id="project-1", name="Project"),
            workflow_template=template,
            workflow_run=run_a,
        )
        context_a.current_task = run_a.tasks[0]
        service.acquire_for_context(context_a)
        original = repository.get_by_canonical_url_for_project(
            "project-1",
            "https://example.com/market-report",
        )
        assert original is not None
        self.assertEqual(original.content_text, "Acquired market report body text.")

        class _AlternateRetriever(DeterministicSourceRetriever):
            def retrieve(self, candidate):
                source = super().retrieve(candidate)
                source.content_text = "version B"
                source.content_checksum = "version-b"
                return source

        service_b = SourceAcquisitionService(
            search_provider=DeterministicSearchProvider(),
            source_retriever=_AlternateRetriever(),
            source_repository=repository,
            query_builder=SearchQueryBuilder(),
        )
        run_b = WorkflowRunFactory(task_factory=TaskFactory()).create(
            template=template,
            run_id="run-b",
        )
        context_b = WorkflowContext(
            project=Project(id="project-1", name="Project"),
            workflow_template=template,
            workflow_run=run_b,
        )
        context_b.current_task = run_b.tasks[0]
        service_b.acquire_for_context(context_b)
        reloaded = repository.get_by_canonical_url_for_project(
            "project-1",
            "https://example.com/market-report",
        )
        assert reloaded is not None
        self.assertEqual(reloaded.id, original.id)
        self.assertEqual(reloaded.content_text, "Acquired market report body text.")
        self.assertIn("run-b", reloaded.workflow_run_refs)

    def test_raises_when_zero_threshold_eligible_sources_acquired(self) -> None:
        design = ResearchDesign(
            id="design-zero-acquired",
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
        template = WorkflowTemplate(
            id="template-zero-acquired",
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
        run.id = "run-zero-acquired"
        context = WorkflowContext(
            project=Project(id="project-zero", name="Project"),
            workflow_template=template,
            workflow_run=run,
        )
        context.current_task = run.tasks[0]

        repository = InMemorySourceRepository()
        service = SourceAcquisitionService(
            search_provider=DeterministicSearchProvider(),
            source_retriever=_AllFailedRetriever(),
            source_repository=repository,
            query_builder=SearchQueryBuilder(),
        )

        with self.assertRaises(SourceAcquisitionError):
            service.acquire_for_context(context)

        persisted = repository.list_for_project("project-zero")
        self.assertGreater(len(persisted), 0, "Failed retrievals should still persist")
        self.assertEqual(
            sum(
                1
                for source in persisted
                if is_successful_acquisition(source.retrieval_status)
            ),
            0,
        )
        self.assertTrue(
            all(
                source.retrieval_status
                in {RetrievalStatus.FAILED, RetrievalStatus.UNSUPPORTED}
                for source in persisted
            ),
        )

        executor = SearchExecutor(source_acquisition_service=service)
        with self.assertRaises(SourceAcquisitionError):
            executor.run(context)
        self.assertNotIn("source_acquisition", context.shared_state)


if __name__ == "__main__":
    unittest.main()

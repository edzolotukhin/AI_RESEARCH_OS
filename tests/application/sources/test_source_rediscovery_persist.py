"""Verify provenance merge persists to repository (PostgreSQL-like behavior)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.project import Project
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template import WorkflowTemplate

from application.sources.provenance_merge import build_discovery_record
from application.sources.search_query_builder import SearchQueryBuilder
from application.sources.source_acquisition_service import SourceAcquisitionService
from infrastructure.search.deterministic_search_adapter import (
    DeterministicSearchProvider,
    DeterministicSourceRetriever,
)
from runtime.workflow_context import WorkflowContext


class _PersistOnSaveSourceRepository:
    def __init__(self) -> None:
        self._sources: dict[str, Source] = {}
        self.save_count = 0

    def get_by_canonical_url_for_project(self, project_id: str, canonical_url: str):
        for source in self._sources.values():
            if source.project_id == project_id and source.canonical_url == canonical_url:
                return self._load(source)
        return None

    def create(self, source: Source) -> int:
        self._sources[source.id] = self._copy(source, version=1)
        return 1

    def get_by_id(self, source_id: str):
        stored = self._sources.get(source_id)
        if stored is None:
            return None
        return self._load(stored)

    def save(self, source: Source, *, expected_version: int | None = None) -> int:
        self.save_count += 1
        next_version = (expected_version or source.version) + 1
        self._sources[source.id] = self._copy(source, version=next_version)
        return next_version

    @staticmethod
    def _copy(source: Source, *, version: int) -> Source:
        return Source(
            id=source.id,
            project_id=source.project_id,
            url=source.url,
            canonical_url=source.canonical_url,
            title=source.title,
            retrieved_at=source.retrieved_at,
            retrieval_status=source.retrieval_status,
            content_text=source.content_text,
            content_checksum=source.content_checksum,
            query_refs=tuple(source.query_refs),
            research_question_refs=tuple(source.research_question_refs),
            information_need_refs=tuple(source.information_need_refs),
            workflow_run_refs=tuple(source.workflow_run_refs),
            research_design_refs=tuple(source.research_design_refs),
            metadata=dict(source.metadata),
            version=version,
        )

    @staticmethod
    def _load(source: Source) -> Source:
        return Source(
            id=source.id,
            project_id=source.project_id,
            url=source.url,
            canonical_url=source.canonical_url,
            title=source.title,
            retrieved_at=source.retrieved_at,
            retrieval_status=source.retrieval_status,
            content_text=source.content_text,
            content_checksum=source.content_checksum,
            query_refs=tuple(source.query_refs),
            research_question_refs=tuple(source.research_question_refs),
            information_need_refs=tuple(source.information_need_refs),
            workflow_run_refs=tuple(source.workflow_run_refs),
            research_design_refs=tuple(source.research_design_refs),
            metadata=dict(source.metadata),
            version=source.version,
        )


class SourceRediscoveryPersistTests(unittest.TestCase):
    def test_re_discovery_persists_run_two_provenance(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        stored = Source(
            id="source-1",
            project_id="project-1",
            url="https://example.com/market-report",
            canonical_url="https://example.com/market-report",
            title="Example Market Report",
            retrieved_at=now,
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text="Acquired market report body text.",
            content_checksum="checksum-a",
            query_refs=("sq-in-rq-1",),
            research_question_refs=("rq-1",),
            information_need_refs=("in-rq-1",),
            workflow_run_refs=("run-1",),
            research_design_refs=("design-1",),
            metadata={
                "discovery_records": [
                    build_discovery_record(
                        provider="deterministic",
                        query_id="sq-in-rq-1",
                        rank=1,
                        workflow_run_id="run-1",
                        research_design_id="design-1",
                        research_question_id="rq-1",
                        information_need_id="in-rq-1",
                    ),
                ],
            },
            version=1,
        )
        repository = _PersistOnSaveSourceRepository()
        repository._sources[stored.id] = stored
        service = SourceAcquisitionService(
            search_provider=DeterministicSearchProvider(),
            source_retriever=DeterministicSourceRetriever(),
            source_repository=repository,
            query_builder=SearchQueryBuilder(),
        )

        design = ResearchDesign(
            id="design-2",
            research_questions=(
                ResearchQuestion(
                    id="rq-1",
                    question="What evidence is required?",
                    objective_refs=("Evaluate brand awareness.",),
                ),
            ),
            information_needs=(
                InformationNeed(
                    id="in-rq-1",
                    research_question_id="rq-1",
                    description="Desk research sources relevant to the linked objective.",
                ),
            ),
        )
        template = WorkflowTemplate(
            id="template-2",
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
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(
            template=template,
            run_id="run-2",
        )
        context = WorkflowContext(
            project=Project(id="project-1", name="Project"),
            workflow_template=template,
            workflow_run=run,
        )

        service.acquire_for_context(context)

        self.assertGreaterEqual(repository.save_count, 1)
        reloaded = repository.get_by_canonical_url_for_project(
            "project-1",
            "https://example.com/market-report",
        )
        assert reloaded is not None
        self.assertIn("run-2", reloaded.workflow_run_refs)
        self.assertIn("design-2", reloaded.research_design_refs)
        records = reloaded.metadata.get("discovery_records") or []
        self.assertTrue(
            any(
                str(record.get("workflow_run_id")) == "run-2"
                and str(record.get("research_design_id")) == "design-2"
                for record in records
            ),
        )


if __name__ == "__main__":
    unittest.main()

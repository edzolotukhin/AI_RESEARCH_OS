"""Unit test reproducing repeated-run evidence failure with same local design IDs."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from uuid import uuid4

from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.project import Project
from domain.sources.retrieval_status import RetrievalStatus
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template import WorkflowTemplate

from application.evidence.evidence_extraction_service import EvidenceExtractionService
from application.evidence.exceptions import EvidenceExtractionError
from application.evidence.run_scoped_provenance import resolve_run_scoped_context
from application.sources.search_query_builder import SearchQueryBuilder
from application.sources.source_acquisition_service import SourceAcquisitionService
from infrastructure.evidence.deterministic_evidence_extractor import (
    DeterministicEvidenceExtractor,
)
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)
from infrastructure.search.deterministic_search_adapter import (
    DeterministicSearchProvider,
    DeterministicSourceRetriever,
)
from runtime.workflow_context import WorkflowContext


def _design(*, design_id: str) -> ResearchDesign:
    return ResearchDesign(
        id=design_id,
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


def _template(*, design: ResearchDesign) -> WorkflowTemplate:
    return WorkflowTemplate(
        id=f"template-{design.id}",
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


class RepeatedRunSameLocalIdsTests(unittest.TestCase):
    def test_second_run_with_new_design_extracts_run_scoped_evidence(self) -> None:
        project_id = "project-repeat"
        design_1 = _design(design_id=str(uuid4()))
        design_2 = _design(design_id=str(uuid4()))
        template_1 = _template(design=design_1)
        template_2 = _template(design=design_2)

        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        acquisition = SourceAcquisitionService(
            search_provider=DeterministicSearchProvider(),
            source_retriever=DeterministicSourceRetriever(),
            source_repository=source_repo,
            query_builder=SearchQueryBuilder(),
        )
        extraction = EvidenceExtractionService(
            evidence_extractor=DeterministicEvidenceExtractor(),
            evidence_repository=evidence_repo,
            source_repository=source_repo,
        )

        run_1 = WorkflowRunFactory(task_factory=TaskFactory()).create(
            template=template_1,
            run_id="run-1",
        )
        context_1 = WorkflowContext(
            project=Project(id=project_id, name="Repeat"),
            workflow_template=template_1,
            workflow_run=run_1,
        )
        acquisition.acquire_for_context(context_1)
        extraction.extract_for_context(context_1)

        shared = source_repo.get_by_canonical_url_for_project(
            project_id,
            "https://example.com/market-report",
        )
        assert shared is not None
        self.assertIn("run-1", shared.workflow_run_refs)
        self.assertIn(design_1.id, shared.research_design_refs)

        run_2 = WorkflowRunFactory(task_factory=TaskFactory()).create(
            template=template_2,
            run_id="run-2",
        )
        context_2 = WorkflowContext(
            project=Project(id=project_id, name="Repeat"),
            workflow_template=template_2,
            workflow_run=run_2,
        )
        acquisition.acquire_for_context(context_2)

        reloaded = source_repo.get_by_canonical_url_for_project(
            project_id,
            "https://example.com/market-report",
        )
        assert reloaded is not None
        self.assertEqual(reloaded.id, shared.id)
        self.assertIn("run-2", reloaded.workflow_run_refs)
        self.assertIn(design_2.id, reloaded.research_design_refs)

        run_2_context = resolve_run_scoped_context(
            source=reloaded,
            design=design_2,
            workflow_run_id="run-2",
            research_design_id=design_2.id,
        )
        self.assertEqual(run_2_context.information_need_ids, ("in-rq-1",))

        summary_2 = extraction.extract_for_context(context_2)
        self.assertGreater(summary_2.evidence_extracted, 0)

        evidence_run_1 = evidence_repo.list_for_project(project_id, workflow_run_id="run-1")
        evidence_run_2 = evidence_repo.list_for_project(project_id, workflow_run_id="run-2")
        self.assertGreater(len(evidence_run_1), 0)
        self.assertGreater(len(evidence_run_2), 0)
        self.assertNotEqual(evidence_run_1[0].id, evidence_run_2[0].id)
        self.assertEqual(evidence_run_2[0].research_design_id, design_2.id)
        self.assertEqual(evidence_run_2[0].workflow_run_id, "run-2")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source

from application.evidence.evidence_extraction_service import EvidenceExtractionService
from application.evidence.exceptions import EvidenceExtractionError
from application.executors.evidence_executor import EvidenceExecutor
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.ports.evidence_ports import EvidenceCandidate, EvidenceExtractor
from domain.evidence.evidence_type import EvidenceType
from infrastructure.evidence.deterministic_evidence_extractor import (
    DeterministicEvidenceExtractor,
)
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)
from runtime.workflow_context import WorkflowContext
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.factories.task_factory import TaskFactory
from domain.project import Project
from domain.workflow_template import WorkflowTemplate
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType


def _design() -> ResearchDesign:
    return ResearchDesign(
        id="design-1",
        research_questions=(
            ResearchQuestion(id="rq-1", question="What is the market outlook?", objective_refs=()),
        ),
        information_needs=(
            InformationNeed(
                id="in-1",
                research_question_id="rq-1",
                description="Need market data",
            ),
        ),
    )


def _template(design: ResearchDesign) -> WorkflowTemplate:
    return WorkflowTemplate(
        id="template-1",
        name="Desk",
        task_definitions=[
            TaskDefinition(
                id="task-extract-evidence",
                name="Extract",
                executor_id="evidence",
                executor_type=ExecutorType.AGENT,
            ),
        ],
        research_design_snapshot=design,
    )


def _source(*, run_id: str, content: str, checksum: str) -> Source:
    now = datetime.now(timezone.utc).isoformat()
    return Source(
        id="source-1",
        project_id="project-1",
        url="https://example.com/report",
        canonical_url="https://example.com/report",
        title="Report",
        retrieved_at=now,
        retrieval_status=RetrievalStatus.ACQUIRED,
        content_text=content,
        content_checksum=checksum,
        workflow_run_refs=(run_id,),
        research_design_refs=("design-1",),
        information_need_refs=("in-1",),
        research_question_refs=("rq-1",),
        metadata={
            "discovery_records": [
                {
                    "provider": "deterministic",
                    "query_id": "sq-in-1",
                    "rank": 1,
                    "workflow_run_id": run_id,
                    "research_design_id": "design-1",
                },
            ],
        },
    )


class EvidenceExtractionServiceTests(unittest.TestCase):
    def test_extracts_grounded_evidence_for_run(self) -> None:
        design = _design()
        template = _template(design)
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
        run.id = "run-1"
        context = WorkflowContext(
            project=Project(id="project-1", name="Project"),
            workflow_template=template,
            workflow_run=run,
        )
        context.current_task = run.tasks[0]

        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        source_repo.create(
            _source(
                run_id="run-1",
                content="Acquired market report body text.",
                checksum="checksum-a",
            ),
        )
        service = EvidenceExtractionService(
            evidence_extractor=DeterministicEvidenceExtractor(),
            evidence_repository=evidence_repo,
            source_repository=source_repo,
        )
        summary = service.extract_for_context(context)
        self.assertGreater(summary.evidence_extracted, 0)
        stored = evidence_repo.list_for_project("project-1", workflow_run_id="run-1")
        self.assertEqual(stored[0].source_content_checksum, "checksum-a")

    def test_zero_valid_evidence_raises(self) -> None:
        design = _design()
        template = _template(design)
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
        context = WorkflowContext(
            project=Project(id="project-1", name="Project"),
            workflow_template=template,
            workflow_run=run,
        )
        context.current_task = run.tasks[0]
        service = EvidenceExtractionService(
            evidence_extractor=DeterministicEvidenceExtractor(),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=InMemorySourceRepository(),
        )
        with self.assertRaises(EvidenceExtractionError):
            service.extract_for_context(context)

    def test_repeated_extraction_does_not_duplicate(self) -> None:
        design = _design()
        template = _template(design)
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
        run.id = "run-1"
        context = WorkflowContext(
            project=Project(id="project-1", name="Project"),
            workflow_template=template,
            workflow_run=run,
        )
        context.current_task = run.tasks[0]
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        source_repo.create(
            _source(
                run_id="run-1",
                content="Acquired market report body text.",
                checksum="checksum-a",
            ),
        )
        service = EvidenceExtractionService(
            evidence_extractor=DeterministicEvidenceExtractor(),
            evidence_repository=evidence_repo,
            source_repository=source_repo,
        )
        first = service.extract_for_context(context)
        second = service.extract_for_context(context)
        self.assertEqual(first.evidence_extracted, second.evidence_extracted)
        self.assertEqual(
            len(evidence_repo.list_for_project("project-1", workflow_run_id="run-1")),
            len(first.evidence_ids),
        )

    def test_ungrounded_candidate_is_skipped_but_other_evidence_succeeds(self) -> None:
        class _MixedExtractor(EvidenceExtractor):
            method_name = "test"

            def extract(self, *, source, design, run_context: RunScopedSourceContext):
                return [
                    EvidenceCandidate(
                        statement="Bad",
                        source_excerpt="not in source",
                        evidence_type=EvidenceType.DIRECT_EXCERPT.value,
                        research_question_refs=run_context.research_question_ids or ("rq-1",),
                        information_need_refs=run_context.information_need_ids or ("in-1",),
                    ),
                    EvidenceCandidate(
                        statement="Good",
                        source_excerpt="Acquired market report body text.",
                        evidence_type=EvidenceType.DIRECT_EXCERPT.value,
                        research_question_refs=run_context.research_question_ids or ("rq-1",),
                        information_need_refs=run_context.information_need_ids or ("in-1",),
                    ),
                ]

        design = _design()
        template = _template(design)
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
        run.id = "run-1"
        context = WorkflowContext(
            project=Project(id="project-1", name="Project"),
            workflow_template=template,
            workflow_run=run,
        )
        context.current_task = run.tasks[0]
        source_repo = InMemorySourceRepository()
        source_repo.create(
            _source(
                run_id="run-1",
                content="Acquired market report body text.",
                checksum="checksum-a",
            ),
        )
        service = EvidenceExtractionService(
            evidence_extractor=_MixedExtractor(),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=source_repo,
        )
        summary = service.extract_for_context(context)
        self.assertEqual(summary.evidence_extracted, 1)
        self.assertEqual(summary.extraction_failures, 1)

    def test_evidence_executor_propagates_zero_evidence_failure(self) -> None:
        design = _design()
        template = _template(design)
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
        context = WorkflowContext(
            project=Project(id="project-1", name="Project"),
            workflow_template=template,
            workflow_run=run,
        )
        context.current_task = run.tasks[0]
        executor = EvidenceExecutor(
            evidence_extraction_service=EvidenceExtractionService(
                evidence_extractor=DeterministicEvidenceExtractor(),
                evidence_repository=InMemoryEvidenceRepository(),
                source_repository=InMemorySourceRepository(),
            ),
        )
        with self.assertRaises(EvidenceExtractionError):
            executor.run(context)
        self.assertNotIn("evidence_extraction", context.shared_state)


if __name__ == "__main__":
    unittest.main()

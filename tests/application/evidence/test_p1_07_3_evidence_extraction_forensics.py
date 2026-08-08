"""P1-07.3 evidence extraction forensics diagnostics tests."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from domain.evidence.evidence_type import EvidenceType
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source

from application.evidence.chunked_evidence_extractor import ChunkedEvidenceExtractor
from application.evidence.content_chunking import split_normalized_source_content
from application.evidence.evidence_extraction_diagnostics import (
    EvidenceStageFailureClassification,
)
from application.evidence.evidence_extraction_service import EvidenceExtractionService
from application.evidence.exceptions import EvidenceExtractionError
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.execution.budget_utils import EVIDENCE_STAGE_CAP_REASON
from application.execution.execution_budget import ExecutionBudget
from application.execution.execution_budget_context import (
    _current_budget,
    ensure_run_budget,
    set_execution_stage,
)
from application.ports.evidence_ports import EvidenceCandidate, EvidenceExtractor
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


def _design(*need_ids: str) -> ResearchDesign:
    needs = tuple(
        InformationNeed(
            id=need_id,
            research_question_id="rq-1",
            description=f"Need {need_id}",
        )
        for need_id in need_ids
    )
    return ResearchDesign(
        id="design-1",
        research_questions=(
            ResearchQuestion(id="rq-1", question="What is the market outlook?", objective_refs=()),
        ),
        information_needs=needs,
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


def _context(*, design: ResearchDesign, run_id: str = "run-forensics") -> WorkflowContext:
    template = _template(design)
    run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
    run.id = run_id
    context = WorkflowContext(
        project=Project(id="project-1", name="Project"),
        workflow_template=template,
        workflow_run=run,
    )
    context.current_task = run.tasks[0]
    return context


def _source(
    *,
    source_id: str,
    run_id: str,
    content: str,
    need_ids: tuple[str, ...] = ("in-1",),
    checksum: str | None = None,
) -> Source:
    now = datetime.now(timezone.utc).isoformat()
    return Source(
        id=source_id,
        project_id="project-1",
        url=f"https://example.com/{source_id}",
        canonical_url=f"https://example.com/{source_id}",
        title=f"Report {source_id}",
        retrieved_at=now,
        retrieval_status=RetrievalStatus.ACQUIRED,
        content_text=content,
        content_checksum=checksum or f"checksum-{source_id}",
        workflow_run_refs=(run_id,),
        research_design_refs=("design-1",),
        information_need_refs=need_ids,
        research_question_refs=("rq-1",),
        metadata={
            "discovery_records": [
                {
                    "provider": "deterministic",
                    "query_id": f"sq-{need_ids[0]}",
                    "rank": 1,
                    "workflow_run_id": run_id,
                    "research_design_id": "design-1",
                },
            ],
        },
    )


class EvidenceForensicsDiagnosticsTests(unittest.TestCase):
    def test_successful_extraction_reports_diagnostics(self) -> None:
        design = _design("in-1")
        context = _context(design=design)
        source_repo = InMemorySourceRepository()
        source_repo.create(
            _source(
                source_id="source-1",
                run_id="run-forensics",
                content="Acquired market report body text.",
            ),
        )
        service = EvidenceExtractionService(
            evidence_extractor=DeterministicEvidenceExtractor(),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=source_repo,
        )
        summary = service.extract_for_context(context)
        self.assertGreater(summary.evidence_extracted, 0)
        self.assertIsNotNone(summary.diagnostics)
        assert summary.diagnostics is not None
        self.assertEqual(
            summary.diagnostics.failure_classification,
            EvidenceStageFailureClassification.SUCCESS.value,
        )
        self.assertEqual(summary.diagnostics.persisted_evidence, summary.evidence_extracted)
        self.assertEqual(len(summary.diagnostics.work_items), 1)
        self.assertEqual(summary.diagnostics.work_items[0].extractor_status, "success")

    def test_extractor_exception_is_visible_in_diagnostics(self) -> None:
        class _ExplodingExtractor(EvidenceExtractor):
            method_name = "explode"

            def extract(self, *, source, design, run_context: RunScopedSourceContext):
                raise TypeError("parser regression")

        design = _design("in-1")
        context = _context(design=design)
        source_repo = InMemorySourceRepository()
        source_repo.create(
            _source(
                source_id="source-1",
                run_id="run-forensics",
                content="Acquired market report body text.",
            ),
        )
        service = EvidenceExtractionService(
            evidence_extractor=_ExplodingExtractor(),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=source_repo,
        )
        with self.assertRaises(EvidenceExtractionError):
            service.extract_for_context(context)

    def test_extractor_exception_diagnostics_on_direct_extract(self) -> None:
        class _ExplodingExtractor(EvidenceExtractor):
            method_name = "explode"

            def extract(self, *, source, design, run_context: RunScopedSourceContext):
                raise TypeError("parser regression")

        design = _design("in-1")
        context = _context(design=design)
        source_repo = InMemorySourceRepository()
        source = _source(
            source_id="source-1",
            run_id="run-forensics",
            content="Acquired market report body text.",
        )
        source_repo.create(source)
        service = EvidenceExtractionService(
            evidence_extractor=_ExplodingExtractor(),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=source_repo,
        )
        diagnostics_holder: list = []

        class _CapturingService(EvidenceExtractionService):
            def _extract_work_queue(self, queue, **kwargs):
                kwargs["allow_empty_failure"] = False
                summary = super()._extract_work_queue(queue, **kwargs)
                diagnostics_holder.append(summary.diagnostics)
                return summary

        capturing = _CapturingService(
            evidence_extractor=_ExplodingExtractor(),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=source_repo,
        )
        summary = capturing.extract_for_context(context)
        self.assertEqual(summary.evidence_extracted, 0)
        diagnostics = diagnostics_holder[0]
        self.assertEqual(diagnostics.extractor_exceptions.get("TypeError"), 1)
        self.assertEqual(diagnostics.work_items[0].exception_class, "TypeError")
        self.assertEqual(diagnostics.work_items[0].exception_message, "parser regression")
        self.assertEqual(
            diagnostics.failure_classification,
            EvidenceStageFailureClassification.EXTRACTOR_FAILURE.value,
        )

    def test_zero_candidates_classified_separately(self) -> None:
        class _EmptyExtractor(EvidenceExtractor):
            method_name = "empty"

            def extract(self, *, source, design, run_context: RunScopedSourceContext):
                return []

        design = _design("in-1")
        context = _context(design=design)
        source_repo = InMemorySourceRepository()
        source_repo.create(
            _source(
                source_id="source-1",
                run_id="run-forensics",
                content="Some unrelated content.",
            ),
        )
        service = EvidenceExtractionService(
            evidence_extractor=_EmptyExtractor(),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=source_repo,
        )
        with self.assertRaises(EvidenceExtractionError):
            service.extract_for_context(context)

        diagnostics_holder: list = []

        class _CapturingService(EvidenceExtractionService):
            def _extract_work_queue(self, queue, **kwargs):
                kwargs["allow_empty_failure"] = False
                summary = super()._extract_work_queue(queue, **kwargs)
                diagnostics_holder.append(summary.diagnostics)
                return summary

        capturing = _CapturingService(
            evidence_extractor=_EmptyExtractor(),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=source_repo,
        )
        capturing.extract_for_context(context)
        diagnostics = diagnostics_holder[0]
        self.assertEqual(diagnostics.work_items[0].extractor_status, "no_candidates")
        self.assertEqual(
            diagnostics.failure_classification,
            EvidenceStageFailureClassification.NO_CANDIDATES.value,
        )

    def test_grounding_rejection_classified(self) -> None:
        class _UngroundedExtractor(EvidenceExtractor):
            method_name = "ungrounded"

            def extract(self, *, source, design, run_context: RunScopedSourceContext):
                return [
                    EvidenceCandidate(
                        statement="Bad",
                        source_excerpt="not in source",
                        evidence_type=EvidenceType.DIRECT_EXCERPT.value,
                        research_question_refs=("rq-1",),
                        information_need_refs=("in-1",),
                    ),
                ]

        design = _design("in-1")
        context = _context(design=design)
        source_repo = InMemorySourceRepository()
        source_repo.create(
            _source(
                source_id="source-1",
                run_id="run-forensics",
                content="Acquired market report body text.",
            ),
        )
        diagnostics_holder: list = []

        class _CapturingService(EvidenceExtractionService):
            def _extract_work_queue(self, queue, **kwargs):
                kwargs["allow_empty_failure"] = False
                summary = super()._extract_work_queue(queue, **kwargs)
                diagnostics_holder.append(summary.diagnostics)
                return summary

        capturing = _CapturingService(
            evidence_extractor=_UngroundedExtractor(),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=source_repo,
        )
        capturing.extract_for_context(context)
        diagnostics = diagnostics_holder[0]
        self.assertEqual(diagnostics.rejected_grounding, 1)
        self.assertEqual(
            diagnostics.failure_classification,
            EvidenceStageFailureClassification.GROUNDING_REJECTED_ALL.value,
        )
        outcome = diagnostics.work_items[0].candidate_outcomes[0]
        self.assertEqual(outcome.rejection_reason, "grounding")
        self.assertEqual(outcome.grounding_detail, "excerpt_not_found")

    def test_provenance_rejection_classified(self) -> None:
        class _BadProvenanceExtractor(EvidenceExtractor):
            method_name = "bad-provenance"

            def extract(self, *, source, design, run_context: RunScopedSourceContext):
                return [
                    EvidenceCandidate(
                        statement="Statement",
                        source_excerpt="Acquired market report body text.",
                        evidence_type=EvidenceType.DIRECT_EXCERPT.value,
                        research_question_refs=("rq-1",),
                        information_need_refs=("missing-need",),
                    ),
                ]

        design = _design("in-1")
        context = _context(design=design)
        source_repo = InMemorySourceRepository()
        source_repo.create(
            _source(
                source_id="source-1",
                run_id="run-forensics",
                content="Acquired market report body text.",
            ),
        )
        diagnostics_holder: list = []

        class _CapturingService(EvidenceExtractionService):
            def _extract_work_queue(self, queue, **kwargs):
                kwargs["allow_empty_failure"] = False
                summary = super()._extract_work_queue(queue, **kwargs)
                diagnostics_holder.append(summary.diagnostics)
                return summary

        capturing = _CapturingService(
            evidence_extractor=_BadProvenanceExtractor(),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=source_repo,
        )
        capturing.extract_for_context(context)
        diagnostics = diagnostics_holder[0]
        self.assertEqual(diagnostics.rejected_invalid_or_missing_need_ref, 1)
        self.assertEqual(
            diagnostics.failure_classification,
            EvidenceStageFailureClassification.INVALID_NEED_REFS_ALL.value,
        )

    def test_budget_stop_classified(self) -> None:
        class _BudgetedEmptyExtractor(EvidenceExtractor):
            method_name = "budgeted-empty"

            def extract(self, *, source, design, run_context: RunScopedSourceContext):
                budget = _current_budget.get()
                if budget is not None:
                    budget.assert_can_call("evidence")
                    budget.record_llm_call("evidence")
                return []

        design = _design("in-1")
        context = _context(design=design, run_id="run-cap")
        source_repo = InMemorySourceRepository()
        for index in range(3):
            source_repo.create(
                _source(
                    source_id=f"source-{index}",
                    run_id="run-cap",
                    content=f"Acquired market report body text {index}.",
                ),
            )
        service = EvidenceExtractionService(
            evidence_extractor=_BudgetedEmptyExtractor(),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=source_repo,
        )
        budget = ExecutionBudget(evidence_max_llm_calls=1)
        ensure_run_budget(context)
        context.execution_metadata["execution_budget"] = budget
        token = _current_budget.set(budget)
        set_execution_stage("evidence")
        self.addCleanup(_current_budget.reset, token)

        with self.assertRaises(EvidenceExtractionError):
            service.extract_for_context(context)

        diagnostics_holder: list = []

        class _CapturingService(EvidenceExtractionService):
            def _extract_work_queue(self, queue, **kwargs):
                kwargs["allow_empty_failure"] = False
                summary = super()._extract_work_queue(queue, **kwargs)
                diagnostics_holder.append(summary.diagnostics)
                return summary

        capturing = _CapturingService(
            evidence_extractor=_BudgetedEmptyExtractor(),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=source_repo,
        )
        budget2 = ExecutionBudget(evidence_max_llm_calls=1)
        context2 = _context(design=design, run_id="run-cap-2")
        ensure_run_budget(context2)
        context2.execution_metadata["execution_budget"] = budget2
        token2 = _current_budget.set(budget2)
        set_execution_stage("evidence")
        self.addCleanup(_current_budget.reset, token2)
        for index in range(3):
            source_repo.create(
                _source(
                    source_id=f"source-b-{index}",
                    run_id="run-cap-2",
                    content=f"Acquired market report body text {index}.",
                ),
            )
        capturing.extract_for_context(context2)
        diagnostics = diagnostics_holder[0]
        self.assertTrue(diagnostics.budget_stop)
        self.assertEqual(diagnostics.budget_stop_reason, EVIDENCE_STAGE_CAP_REASON)
        self.assertEqual(diagnostics.extractor_attempts, 1)

    def test_mixed_failure_classification(self) -> None:
        class _MixedExtractor(EvidenceExtractor):
            method_name = "mixed"

            def extract(self, *, source, design, run_context: RunScopedSourceContext):
                return [
                    EvidenceCandidate(
                        statement="Bad",
                        source_excerpt="not in source",
                        evidence_type=EvidenceType.DIRECT_EXCERPT.value,
                        research_question_refs=("rq-1",),
                        information_need_refs=("in-1",),
                    ),
                    EvidenceCandidate(
                        statement="Good",
                        source_excerpt="Acquired market report body text.",
                        evidence_type=EvidenceType.DIRECT_EXCERPT.value,
                        research_question_refs=("rq-1",),
                        information_need_refs=("in-1",),
                    ),
                ]

        design = _design("in-1")
        context = _context(design=design)
        source_repo = InMemorySourceRepository()
        source_repo.create(
            _source(
                source_id="source-1",
                run_id="run-forensics",
                content="Acquired market report body text.",
            ),
        )
        service = EvidenceExtractionService(
            evidence_extractor=_MixedExtractor(),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=source_repo,
        )
        summary = service.extract_for_context(context)
        self.assertEqual(summary.evidence_extracted, 1)
        assert summary.diagnostics is not None
        self.assertEqual(
            summary.diagnostics.failure_classification,
            EvidenceStageFailureClassification.MIXED_FAILURE.value,
        )

    def test_double_chunking_boundaries_observable(self) -> None:
        long_content = "Acquired market report body text. " + ("x" * 12000)
        design = _design("in-1", "in-2")
        context = _context(design=design)
        source_repo = InMemorySourceRepository()
        source_repo.create(
            _source(
                source_id="source-large",
                run_id="run-forensics",
                content=long_content,
                need_ids=("in-1",),
            ),
        )
        inner = DeterministicEvidenceExtractor()
        chunked = ChunkedEvidenceExtractor(inner, chunk_chars=8000, overlap_chars=500)
        service = EvidenceExtractionService(
            evidence_extractor=chunked,
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=source_repo,
        )
        summary = service.extract_for_context(context)
        assert summary.diagnostics is not None
        self.assertGreater(summary.diagnostics.outer_chunks, 1)
        self.assertGreater(summary.diagnostics.inner_chunks_observed, 0)
        work_item = summary.diagnostics.work_items[0]
        self.assertGreater(work_item.outer_chunk_length, 0)
        self.assertGreater(len(work_item.inner_chunks), 0)
        inner_chunk = work_item.inner_chunks[0]
        self.assertEqual(inner_chunk.inner_chunk_normalized_start, 0)

    def test_coordinate_diagnostics_expose_offset_mismatch(self) -> None:
        from application.evidence.evidence_extraction_diagnostics import (
            classify_grounding_failure,
        )

        chunk_local = "Acquired market report body text."
        detail = classify_grounding_failure(
            source_text=chunk_local,
            excerpt="Acquired market report body text.",
            chunk_normalized_start=9000,
            chunk_normalized_end=9034,
        )
        self.assertEqual(detail, "offset_mismatch")

        prefix = "padding text " * 800
        content = prefix + "Acquired market report body text."
        design = _design("in-1")
        context = _context(design=design)
        source_repo = InMemorySourceRepository()
        source_repo.create(
            _source(
                source_id="source-1",
                run_id="run-forensics",
                content=content,
            ),
        )
        service = EvidenceExtractionService(
            evidence_extractor=DeterministicEvidenceExtractor(),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=source_repo,
        )
        summary = service.extract_for_context(context)
        assert summary.diagnostics is not None
        non_zero_window = [
            item
            for item in summary.diagnostics.work_items
            if item.grounding_search_start not in (None, 0)
        ]
        self.assertTrue(
            non_zero_window,
            "Expected outer chunk absolute coordinates on later work items",
        )

    def test_fair_scheduler_order_unchanged_with_diagnostics(self) -> None:
        from application.evidence.evidence_extraction_scheduler import (
            build_need_fair_extraction_queue,
        )

        long_a = "Acquired market report body text. " + ("a" * 12000)
        design = _design("in-1", "in-2", "in-3")
        sources = [
            _source(source_id="src-a", run_id="run-forensics", content=long_a, need_ids=("in-1",)),
            _source(source_id="src-b", run_id="run-forensics", content="Body b text.", need_ids=("in-2",)),
            _source(source_id="src-c", run_id="run-forensics", content="Body c text.", need_ids=("in-3",)),
        ]
        queue = build_need_fair_extraction_queue(
            sources,
            design=design,
            workflow_run_id="run-forensics",
            research_design_id="design-1",
            chunk_chars=8000,
            overlap_chars=500,
        )
        first_three = [item.source.id for item in queue[:3]]
        self.assertEqual(first_three, ["src-a", "src-b", "src-c"])


if __name__ == "__main__":
    unittest.main()

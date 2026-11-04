"""P1-07.3.1 failure-path evidence diagnostics persistence tests."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from unittest import mock
from unittest.mock import patch

from domain.evidence.evidence_type import EvidenceType
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source
from domain.value_objects.task_status import TaskStatus

from application.evidence.evidence_extraction_service import EvidenceExtractionService
from application.evidence.evidence_extraction_diagnostics import classify_extraction_exception
from application.evidence.evidence_extraction_diagnostics import (
    InnerChunkObservation,
    WorkItemTrace,
)
from application.evidence.evidence_result_codec import extract_evidence_extraction
from application.evidence.exceptions import EvidenceExtractionError
from application.evidence.exceptions import EvidenceConfigurationError
from application.evidence.evidence_failure_diagnostics_persistence import (
    has_evidence_failure_diagnostics,
)
from application.executors.evidence_executor import EvidenceExecutor
from application.runtime.workflow_runtime_persister import WorkflowRuntimePersister
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.ports.evidence_ports import EvidenceCandidate, EvidenceExtractor
from infrastructure.evidence.deterministic_evidence_extractor import (
    DeterministicEvidenceExtractor,
)
from infrastructure.evidence.llm_evidence_extractor import LlmEvidenceExtractor
from application.authority_extension.selected_workflow import ExtensionBudgetExceeded
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)


class _ClassifiedFailure(Exception):
    def __init__(self, classification):
        super().__init__("bounded test failure")
        self.classification = classification


class ExceptionClassificationTests(unittest.TestCase):
    def test_classification_is_bounded_and_type_checked(self) -> None:
        cases = (
            ("invalid_json", "invalid_response"),
            ("schema_contract_mismatch", "invalid_response"),
            ("unknown_string", "unknown_failure"),
            ([], "unknown_failure"),
            ({"classification": "invalid_json"}, "unknown_failure"),
            (object(), "unknown_failure"),
            (1, "unknown_failure"),
            ("", "unknown_failure"),
        )
        for classification, expected in cases:
            with self.subTest(classification=repr(classification)):
                self.assertEqual(
                    classify_extraction_exception(_ClassifiedFailure(classification)),
                    expected,
                )

    def test_budget_failure_keeps_bounded_phase_and_category(self) -> None:
        failure = _ClassifiedFailure("budget_exhausted")
        failure.failure_category = "budget_exhausted"
        failure.failure_phase = "before_dispatch"
        failure.retry_ambiguous = False
        self.assertEqual(
            classify_extraction_exception(failure),
            "budget_exhausted",
        )

    def test_budget_failure_remains_distinct_from_configuration_failure(self) -> None:
        class FailingClient:
            def generate(self, prompt, *, options=None):
                error = ExtensionBudgetExceeded("private budget detail")
                error.operation_id = "bounded-op-1"
                raise error

        extractor = LlmEvidenceExtractor(llm_client=FailingClient())
        with self.assertRaises(ExtensionBudgetExceeded):
            extractor.extract(
                source=_source(),
                design=_design(),
                run_context=RunScopedSourceContext(
                    workflow_run_id="run-failure-diagnostics",
                    research_design_id="design-1",
                    information_need_ids=("in-1",),
                    research_question_ids=("rq-1",),
                    query_ids=("sq-in-1",),
                ),
            )
    def test_safe_failure_metadata_is_bounded_and_message_free(self) -> None:
        sensitive = "secret-token=do-not-persist"
        inner = InnerChunkObservation(
            inner_chunk_index=0,
            inner_chunk_normalized_start=0,
            inner_chunk_normalized_end=10,
            inner_chunk_length=10,
            extractor_status="exception",
            exception_class="RuntimeError",
            exception_message=sensitive,
            failure_category=["budget_exhausted"],
            failure_phase={"phase": "after_dispatch"},
            operation_id="x" * 1000,
        )
        trace = WorkItemTrace(
            queue_index=0,
            source_id="source-1",
            source_content_checksum="checksum-a",
            information_need_ids=("in-1",),
            outer_chunk_index=0,
            outer_chunk_normalized_start=0,
            outer_chunk_normalized_end=10,
            outer_chunk_length=10,
            failure_categories=["budget_exhausted"],
            failure_phase={"bad": True},
            operation_id=object(),
            inner_chunks=[inner],
        )
        payload = trace.to_dict()
        encoded = json.dumps(payload)
        self.assertNotIn(sensitive, encoded)
        self.assertEqual(payload["failure_phase"], "unknown")
        self.assertNotIn("operation_id", payload)
        nested = payload["inner_chunks"][0]
        self.assertEqual(nested["failure_category"], "unknown_failure")
        self.assertEqual(nested["failure_phase"], "unknown")
        self.assertLessEqual(len(nested["operation_id"]), 128)

    def test_llm_extractor_preserves_safe_inner_failure_metadata(self) -> None:
        class FailingClient:
            def generate(self, prompt, *, options=None):
                error = RuntimeError("private provider payload")
                error.failure_phase = "after_dispatch"
                error.retry_ambiguous = True
                error.operation_id = "bounded-op-1"
                raise error

        extractor = LlmEvidenceExtractor(llm_client=FailingClient())
        with self.assertRaises(EvidenceConfigurationError) as raised:
            extractor.extract(
                source=_source(),
                design=_design(),
                run_context=RunScopedSourceContext(
                    workflow_run_id="run-failure-diagnostics",
                    research_design_id="design-1",
                    information_need_ids=("in-1",),
                    research_question_ids=("rq-1",),
                    query_ids=("sq-in-1",),
                ),
            )
        error = raised.exception
        self.assertEqual(error.original_exception_class, "RuntimeError")
        self.assertEqual(error.failure_category, "provider_exception")
        self.assertEqual(error.failure_phase, "after_dispatch")
        self.assertTrue(error.retry_ambiguous)
        self.assertEqual(error.operation_id, "bounded-op-1")
        self.assertNotIn("private provider payload", str(error))
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


def _context(*, design: ResearchDesign | None = None) -> WorkflowContext:
    design = design or _design()
    template = _template(design)
    run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
    run.id = "run-failure-diagnostics"
    context = WorkflowContext(
        project=Project(id="project-1", name="Project"),
        workflow_template=template,
        workflow_run=run,
    )
    context.current_task = run.tasks[0]
    return context


def _source(*, content: str = "Acquired market report body text.") -> Source:
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
        content_checksum="checksum-a",
        workflow_run_refs=("run-failure-diagnostics",),
        research_design_refs=("design-1",),
        information_need_refs=("in-1",),
        research_question_refs=("rq-1",),
        metadata={
            "discovery_records": [
                {
                    "provider": "deterministic",
                    "query_id": "sq-in-1",
                    "rank": 1,
                    "workflow_run_id": "run-failure-diagnostics",
                    "research_design_id": "design-1",
                },
            ],
        },
    )


class _EmptyExtractor(EvidenceExtractor):
    method_name = "empty"

    def extract(self, *, source, design, run_context: RunScopedSourceContext):
        return []


class _ExplodingExtractor(EvidenceExtractor):
    method_name = "explode"

    def extract(self, *, source, design, run_context: RunScopedSourceContext):
        raise TypeError("parser regression")


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


class FailurePathDiagnosticsPersistenceTests(unittest.TestCase):
    def _executor_with_sources(
        self,
        extractor: EvidenceExtractor,
        *,
        content: str = "Acquired market report body text.",
    ) -> tuple[EvidenceExecutor, WorkflowContext]:
        context = _context()
        source_repo = InMemorySourceRepository()
        source_repo.create(_source(content=content))
        executor = EvidenceExecutor(
            evidence_extraction_service=EvidenceExtractionService(
                evidence_extractor=extractor,
                evidence_repository=InMemoryEvidenceRepository(),
                source_repository=source_repo,
            ),
        )
        return executor, context

    def test_successful_extraction_unchanged(self) -> None:
        executor, context = self._executor_with_sources(DeterministicEvidenceExtractor())
        executor.run(context)
        payload = context.shared_state["evidence_extraction"]
        self.assertIn("diagnostics", payload)
        self.assertGreater(payload["evidence_extracted"], 0)

    def test_zero_evidence_persists_diagnostics_before_failure(self) -> None:
        executor, context = self._executor_with_sources(_EmptyExtractor())
        with self.assertRaises(EvidenceExtractionError):
            executor.run(context)
        payload = context.shared_state["evidence_extraction"]
        diagnostics = payload["diagnostics"]
        self.assertEqual(diagnostics["failure_classification"], "no_candidates")
        self.assertEqual(diagnostics["persisted_evidence"], 0)
        self.assertNotIn("failure_categories", diagnostics["work_items"][0])
        self.assertTrue(has_evidence_failure_diagnostics(context))

    def test_extractor_exception_diagnostics_survive_failure(self) -> None:
        executor, context = self._executor_with_sources(_ExplodingExtractor())
        with self.assertRaises(EvidenceExtractionError):
            executor.run(context)
        diagnostics = context.shared_state["evidence_extraction"]["diagnostics"]
        self.assertEqual(diagnostics["extractor_exceptions"].get("TypeError"), 1)
        self.assertEqual(diagnostics["work_items"][0]["exception_class"], "TypeError")
        self.assertEqual(
            diagnostics["work_items"][0]["failure_categories"],
            ["unknown_failure"],
        )
        self.assertNotIn("exception_message", diagnostics["work_items"][0])

    def test_grounding_rejected_all_diagnostics_survive_failure(self) -> None:
        executor, context = self._executor_with_sources(_UngroundedExtractor())
        with self.assertRaises(EvidenceExtractionError):
            executor.run(context)
        diagnostics = context.shared_state["evidence_extraction"]["diagnostics"]
        self.assertEqual(diagnostics["failure_classification"], "grounding_rejected_all")
        self.assertEqual(diagnostics["rejected_grounding"], 1)
        self.assertIn(
            "grounding_rejection",
            diagnostics["work_items"][0]["failure_categories"],
        )

    def test_provenance_rejected_all_diagnostics_survive_failure(self) -> None:
        executor, context = self._executor_with_sources(_BadProvenanceExtractor())
        with self.assertRaises(EvidenceExtractionError):
            executor.run(context)
        diagnostics = context.shared_state["evidence_extraction"]["diagnostics"]
        self.assertEqual(diagnostics["failure_classification"], "invalid_need_refs_all")
        self.assertIn(
            "provenance_rejection",
            diagnostics["work_items"][0]["failure_categories"],
        )

    def test_mixed_failure_diagnostics_survive_when_not_allow_empty(self) -> None:
        context = _context()
        source_repo = InMemorySourceRepository()
        source_repo.create(_source())
        service = EvidenceExtractionService(
            evidence_extractor=_MixedExtractor(),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=source_repo,
        )
        summary = service.extract_for_source_ids(context, ("source-1",), allow_empty=True)
        self.assertEqual(summary.evidence_extracted, 1)
        self.assertEqual(summary.diagnostics.failure_classification, "mixed_failure")

    def test_diagnostics_persistence_failure_does_not_replace_evidence_error(self) -> None:
        executor, context = self._executor_with_sources(_EmptyExtractor())
        with patch(
            "application.executors.evidence_executor.try_persist_evidence_failure_diagnostics",
            return_value=RuntimeError("persist failed"),
        ):
            with self.assertRaises(EvidenceExtractionError):
                executor.run(context)
        errors = context.execution_metadata["evidence_diagnostics_persistence_errors"]
        self.assertEqual(errors[0]["error_type"], "RuntimeError")

    def test_failed_task_snapshot_is_json_serializable(self) -> None:
        executor, context = self._executor_with_sources(_EmptyExtractor())
        task = context.current_task
        assert task is not None
        with self.assertRaises(EvidenceExtractionError):
            executor.run(context)
        snapshot = context.intermediate_results[task.id]
        json.dumps(snapshot)
        diagnostics = snapshot["shared_state"]["evidence_extraction"]["diagnostics"]
        self.assertIn("work_items", diagnostics)

    def test_durable_persister_captures_failed_evidence_task_snapshot(self) -> None:
        executor, context = self._executor_with_sources(_EmptyExtractor())
        task = context.current_task
        assert task is not None
        with self.assertRaises(EvidenceExtractionError):
            executor.run(context)
        task.ready()
        task.start()
        task.fail()

        persister = WorkflowRuntimePersister(
            workflow_service=mock.Mock(),
            audit=mock.Mock(),
            run_id=context.workflow_run.id,
        )
        persister.on_task_finished(context, error=EvidenceExtractionError("failed"))
        self.assertIn(task.id, persister.task_results)
        payload = extract_evidence_extraction(persister.task_results)
        assert payload is not None
        self.assertEqual(payload["diagnostics"]["failure_classification"], "no_candidates")


if __name__ == "__main__":
    unittest.main()

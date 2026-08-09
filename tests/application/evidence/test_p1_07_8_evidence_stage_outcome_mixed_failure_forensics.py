"""P1-07.8 forensic snapshots of current Evidence stage failure_classification."""

from __future__ import annotations

import ast
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from domain.ai.llm_response import LLMResponse
from domain.evidence.evidence_type import EvidenceType
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source

from application.evidence.chunked_evidence_extractor import ChunkedEvidenceExtractor
from application.evidence.evidence_extraction_diagnostics import (
    EvidenceExtractionDiagnostics,
    EvidenceStageFailureClassification,
)
from application.evidence.evidence_extraction_service import EvidenceExtractionService
from application.evidence.exceptions import EvidenceResponseOutcomeError
from application.evidence.evidence_response_classification import EvidenceResponseClassification
from application.execution.budget_utils import EVIDENCE_STAGE_CAP_REASON
from application.execution.execution_budget import ExecutionBudget
from application.execution.execution_budget_context import (
    _current_budget,
    ensure_run_budget,
    set_execution_stage,
)
from application.ports.evidence_ports import EvidenceCandidate, EvidenceExtractor
from infrastructure.evidence.llm_evidence_extractor import LlmEvidenceExtractor
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

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_TEXT = "Exact excerpt in source. Acquired market report body text."
VALID_ITEM = {
    "statement": "Market size is growing.",
    "source_excerpt": "Exact excerpt in source.",
    "information_need_id": "in-1",
}


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


def _context(*, run_id: str = "run-p1-07-8") -> WorkflowContext:
    design = _design("in-1")
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


def _source(*, source_id: str, run_id: str, content: str = SOURCE_TEXT) -> Source:
    now = datetime.now(timezone.utc).isoformat()
    return Source(
        id=source_id,
        project_id="project-1",
        url=f"https://example.com/{source_id}",
        canonical_url=f"https://example.com/{source_id}",
        title=source_id,
        retrieved_at=now,
        retrieval_status=RetrievalStatus.ACQUIRED,
        content_text=content,
        content_checksum=f"checksum-{source_id}",
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


def _candidate(*, excerpt: str, statement: str = "Market size is growing.") -> EvidenceCandidate:
    return EvidenceCandidate(
        statement=statement,
        source_excerpt=excerpt,
        evidence_type=EvidenceType.DIRECT_EXCERPT.value,
        research_question_refs=("rq-1",),
        information_need_refs=("in-1",),
    )


def _llm_client(responses: list[LLMResponse]) -> Mock:
    client = Mock()
    client.generate.side_effect = list(responses)
    return client


def _chunked_llm(responses: list[LLMResponse]) -> ChunkedEvidenceExtractor:
    return ChunkedEvidenceExtractor(
        LlmEvidenceExtractor(llm_client=_llm_client(responses)),
        chunk_chars=8000,
        overlap_chars=0,
    )


def _service(
    extractor: EvidenceExtractor,
    sources: list[Source],
    *,
    run_id: str,
) -> tuple[EvidenceExtractionService, WorkflowContext]:
    context = _context(run_id=run_id)
    source_repo = InMemorySourceRepository()
    for source in sources:
        source_repo.create(source)
    service = EvidenceExtractionService(
        evidence_extractor=extractor,
        evidence_repository=InMemoryEvidenceRepository(),
        source_repository=source_repo,
    )
    return service, context


class TaxonomyAndDecisionTableTests(unittest.TestCase):
    def test_complete_enum_values(self) -> None:
        self.assertEqual(
            {member.value for member in EvidenceStageFailureClassification},
            {
                "no_eligible_sources",
                "no_run_scoped_context",
                "empty_extraction_queue",
                "extractor_failure",
                "no_candidates",
                "invalid_need_refs_all",
                "provenance_rejected_all",
                "grounding_rejected_all",
                "budget_exhausted_before_evidence",
                "mixed_failure",
                "success",
            },
        )

    def test_persisted_without_rejections_is_success(self) -> None:
        diagnostics = EvidenceExtractionDiagnostics(workflow_run_id="run-1")
        self.assertEqual(
            diagnostics.classify(persisted_evidence=16, budget_stop_before_any_attempt=False),
            "success",
        )

    def test_persisted_with_any_rejection_is_mixed_failure(self) -> None:
        diagnostics = EvidenceExtractionDiagnostics(workflow_run_id="run-1")
        diagnostics.rejected_grounding = 3
        self.assertEqual(
            diagnostics.classify(persisted_evidence=16, budget_stop_before_any_attempt=False),
            "mixed_failure",
        )

    def test_budget_stop_flag_does_not_change_success(self) -> None:
        diagnostics = EvidenceExtractionDiagnostics(workflow_run_id="run-1")
        diagnostics.budget_stop = True
        diagnostics.budget_stop_reason = EVIDENCE_STAGE_CAP_REASON
        self.assertEqual(
            diagnostics.classify(persisted_evidence=16, budget_stop_before_any_attempt=False),
            "success",
        )

    def test_empty_or_invalid_rejection_is_mixed_when_persisted(self) -> None:
        diagnostics = EvidenceExtractionDiagnostics(workflow_run_id="run-1")
        diagnostics.rejected_empty_or_invalid_candidate = 1
        self.assertEqual(
            diagnostics.classify(persisted_evidence=2, budget_stop_before_any_attempt=False),
            "mixed_failure",
        )

    def test_dedup_hits_do_not_count_as_rejections(self) -> None:
        diagnostics = EvidenceExtractionDiagnostics(workflow_run_id="run-1")
        diagnostics.dedup_hits = 3
        self.assertEqual(
            diagnostics.classify(persisted_evidence=16, budget_stop_before_any_attempt=False),
            "success",
        )


class LiveShapedSnapshotTests(unittest.TestCase):
    def test_case_a_all_persisted_is_success(self) -> None:
        extractor = _chunked_llm(
            [LLMResponse(content=json.dumps({"items": [VALID_ITEM]}), finish_reason="stop")],
        )
        service, context = _service(
            extractor,
            [_source(source_id="source-1", run_id="run-a")],
            run_id="run-a",
        )
        summary = service.extract_for_source_ids(context, ("source-1",), allow_empty=True)
        diagnostics = summary.diagnostics
        assert diagnostics is not None
        self.assertGreater(summary.evidence_extracted, 0)
        self.assertEqual(diagnostics.failure_classification, "success")
        self.assertEqual(diagnostics.persisted_evidence, diagnostics.raw_candidates)
        self.assertEqual(
            diagnostics.response_classification_counts.get("valid_candidates"),
            1,
        )

    def test_case_b_partial_candidate_rejection_is_mixed_failure(self) -> None:
        class _MixedExtractor(EvidenceExtractor):
            method_name = "mixed"

            def extract(self, *, source, design, run_context):
                return [
                    _candidate(excerpt="not in source", statement="Rejected"),
                    _candidate(excerpt="Exact excerpt in source."),
                ]

        service, context = _service(
            ChunkedEvidenceExtractor(_MixedExtractor(), chunk_chars=8000, overlap_chars=0),
            [_source(source_id="source-1", run_id="run-b")],
            run_id="run-b",
        )
        summary = service.extract_for_source_ids(context, ("source-1",), allow_empty=True)
        diagnostics = summary.diagnostics
        assert diagnostics is not None
        self.assertEqual(summary.evidence_extracted, 1)
        self.assertEqual(diagnostics.raw_candidates, 2)
        self.assertEqual(diagnostics.rejected_grounding, 1)
        self.assertEqual(diagnostics.failure_classification, "mixed_failure")
        self.assertEqual(
            diagnostics.raw_candidates
            - diagnostics.persisted_evidence
            - diagnostics.rejected_empty_or_invalid_candidate
            - diagnostics.rejected_invalid_or_missing_need_ref
            - diagnostics.rejected_provenance
            - diagnostics.rejected_grounding,
            0,
        )

    def test_case_c_valid_empty_only_is_no_candidates(self) -> None:
        extractor = _chunked_llm(
            [LLMResponse(content=json.dumps({"items": []}), finish_reason="stop")],
        )
        service, context = _service(
            extractor,
            [_source(source_id="source-1", run_id="run-c")],
            run_id="run-c",
        )
        summary = service.extract_for_source_ids(context, ("source-1",), allow_empty=True)
        diagnostics = summary.diagnostics
        assert diagnostics is not None
        self.assertEqual(summary.evidence_extracted, 0)
        self.assertEqual(diagnostics.failure_classification, "no_candidates")
        self.assertEqual(
            diagnostics.response_classification_counts.get("valid_empty_result"),
            1,
        )
        self.assertEqual(diagnostics.extractor_failures, 0)
        self.assertEqual(diagnostics.work_items[0].extractor_status, "no_candidates")
        self.assertEqual(diagnostics.work_items[0].inner_chunks[0].extractor_status, "success")

    def test_case_d_valid_candidates_plus_valid_empty_is_success(self) -> None:
        extractor = _chunked_llm(
            [
                LLMResponse(content=json.dumps({"items": [VALID_ITEM]}), finish_reason="stop"),
                LLMResponse(content=json.dumps({"items": []}), finish_reason="stop"),
            ],
        )
        sources = [
            _source(source_id="source-1", run_id="run-d"),
            _source(source_id="source-2", run_id="run-d"),
        ]
        service, context = _service(extractor, sources, run_id="run-d")
        summary = service.extract_for_source_ids(
            context,
            ("source-1", "source-2"),
            allow_empty=True,
        )
        diagnostics = summary.diagnostics
        assert diagnostics is not None
        self.assertGreater(summary.evidence_extracted, 0)
        self.assertEqual(diagnostics.failure_classification, "success")
        self.assertGreaterEqual(
            diagnostics.response_classification_counts.get("valid_candidates", 0),
            1,
        )
        self.assertGreaterEqual(
            diagnostics.response_classification_counts.get("valid_empty_result", 0),
            1,
        )

    def test_case_e_incomplete_plus_persisted_is_success(self) -> None:
        extractor = _chunked_llm(
            [
                LLMResponse(
                    content="",
                    finish_reason="length",
                    incomplete_reason="max_output_tokens",
                ),
                LLMResponse(content=json.dumps({"items": [VALID_ITEM]}), finish_reason="stop"),
            ],
        )
        sources = [
            _source(source_id="source-1", run_id="run-e"),
            _source(source_id="source-2", run_id="run-e"),
        ]
        service, context = _service(extractor, sources, run_id="run-e")
        summary = service.extract_for_source_ids(
            context,
            ("source-1", "source-2"),
            allow_empty=True,
        )
        diagnostics = summary.diagnostics
        assert diagnostics is not None
        self.assertGreater(summary.evidence_extracted, 0)
        self.assertEqual(diagnostics.failure_classification, "success")
        self.assertEqual(diagnostics.extractor_failures, 0)
        self.assertEqual(
            diagnostics.response_classification_counts.get(
                EvidenceResponseClassification.INCOMPLETE_PROVIDER_OUTPUT.value,
            ),
            1,
        )
        self.assertEqual(
            diagnostics.response_classification_counts.get("valid_candidates"),
            1,
        )

    def test_case_f_all_incomplete_is_no_candidates_on_chunked_path(self) -> None:
        extractor = _chunked_llm(
            [
                LLMResponse(
                    content="",
                    finish_reason="length",
                    incomplete_reason="max_output_tokens",
                ),
            ],
        )
        service, context = _service(
            extractor,
            [_source(source_id="source-1", run_id="run-f")],
            run_id="run-f",
        )
        summary = service.extract_for_source_ids(context, ("source-1",), allow_empty=True)
        diagnostics = summary.diagnostics
        assert diagnostics is not None
        self.assertEqual(summary.evidence_extracted, 0)
        self.assertEqual(diagnostics.failure_classification, "no_candidates")
        self.assertEqual(diagnostics.extractor_failures, 0)
        self.assertEqual(
            diagnostics.response_classification_counts.get("incomplete_provider_output"),
            1,
        )
        self.assertEqual(diagnostics.work_items[0].extractor_status, "no_candidates")
        self.assertEqual(diagnostics.work_items[0].inner_chunks[0].extractor_status, "exception")
        self.assertEqual(
            diagnostics.work_items[0].inner_chunks[0].exception_class,
            EvidenceResponseOutcomeError.__name__,
        )

    def test_case_g_budget_stop_with_persisted_evidence_is_success(self) -> None:
        class _BudgetedExtractor(EvidenceExtractor):
            method_name = "budgeted"

            def extract(self, *, source, design, run_context):
                budget = _current_budget.get()
                if budget is not None:
                    budget.assert_can_call("evidence")
                    budget.record_llm_call("evidence")
                return [_candidate(excerpt="Exact excerpt in source.")]

        run_id = "run-g"
        sources = [
            _source(source_id=f"source-{index}", run_id=run_id)
            for index in range(5)
        ]
        service, context = _service(
            ChunkedEvidenceExtractor(_BudgetedExtractor(), chunk_chars=8000, overlap_chars=0),
            sources,
            run_id=run_id,
        )
        budget = ExecutionBudget(llm_max_calls_per_run=100, evidence_max_llm_calls=2)
        ensure_run_budget(context)
        context.execution_metadata["execution_budget"] = budget
        token = _current_budget.set(budget)
        set_execution_stage("evidence")
        self.addCleanup(_current_budget.reset, token)
        summary = service.extract_for_context(context)
        diagnostics = summary.diagnostics
        assert diagnostics is not None
        self.assertGreater(summary.evidence_extracted, 0)
        self.assertEqual(summary.budget_stop_reason, EVIDENCE_STAGE_CAP_REASON)
        self.assertTrue(diagnostics.budget_stop)
        self.assertEqual(diagnostics.failure_classification, "success")

    def test_case_h_source_without_evidence_plus_persisted_is_success(self) -> None:
        extractor = _chunked_llm(
            [
                LLMResponse(content=json.dumps({"items": [VALID_ITEM]}), finish_reason="stop"),
                LLMResponse(content=json.dumps({"items": []}), finish_reason="stop"),
            ],
        )
        sources = [
            _source(source_id="source-1", run_id="run-h"),
            _source(source_id="source-2", run_id="run-h"),
        ]
        service, context = _service(extractor, sources, run_id="run-h")
        summary = service.extract_for_source_ids(
            context,
            ("source-1", "source-2"),
            allow_empty=True,
        )
        diagnostics = summary.diagnostics
        assert diagnostics is not None
        self.assertGreater(summary.evidence_extracted, 0)
        self.assertGreater(summary.sources_without_evidence, 0)
        self.assertEqual(diagnostics.failure_classification, "success")


class DownstreamConsumerForensicsTests(unittest.TestCase):
    def test_failure_classification_not_read_by_readiness_or_runtime_control(self) -> None:
        forbidden_roots = [
            REPO_ROOT / "application" / "research_quality",
            REPO_ROOT / "application" / "runtime",
            REPO_ROOT / "application" / "executors" / "research_readiness_executor.py",
            REPO_ROOT / "application" / "executors" / "analysis_executor.py",
            REPO_ROOT / "application" / "executors" / "report_executor.py",
            REPO_ROOT / "application" / "executors" / "review_executor.py",
            REPO_ROOT / "application" / "task_scheduler.py",
            REPO_ROOT / "api",
        ]
        files: list[Path] = []
        for root in forbidden_roots:
            if root.is_file():
                files.append(root)
            elif root.is_dir():
                files.extend(root.rglob("*.py"))
        for path in files:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "failure_classification":
                    self.fail(f"{path} reads failure_classification")
                if isinstance(node, ast.Constant) and node.value == "failure_classification":
                    self.fail(f"{path} mentions failure_classification literal")


if __name__ == "__main__":
    unittest.main()

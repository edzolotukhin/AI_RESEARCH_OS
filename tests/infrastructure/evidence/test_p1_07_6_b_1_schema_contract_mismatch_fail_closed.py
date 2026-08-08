"""P1-07.6B.1 SCHEMA_CONTRACT_MISMATCH fail-closed alignment tests."""

from __future__ import annotations

import json
import unittest
from unittest import mock
from unittest.mock import Mock

from domain.ai.llm_response import LLMResponse
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.project import Project
from domain.workflow_template import WorkflowTemplate

from application.evidence.chunked_evidence_extractor import ChunkedEvidenceExtractor
from application.evidence.evidence_extraction_service import EvidenceExtractionService
from application.evidence.evidence_extractor_response_shape import consume_response_shape
from application.evidence.evidence_response_classification import EvidenceResponseClassification
from application.evidence.exceptions import (
    EvidenceExtractionError,
    EvidenceResponseOutcomeError,
)
from application.evidence.evidence_result_codec import extract_evidence_extraction
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.executors.evidence_executor import EvidenceExecutor
from application.runtime.workflow_runtime_persister import WorkflowRuntimePersister
from infrastructure.evidence.llm_evidence_extractor import LlmEvidenceExtractor
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)
from runtime.workflow_context import WorkflowContext


def _design(*need_ids: str) -> ResearchDesign:
    needs = tuple(
        InformationNeed(
            id=need_id,
            research_question_id="RQ1",
            description=f"Need {need_id}",
        )
        for need_id in need_ids
    )
    return ResearchDesign(
        id="design-1",
        language="en",
        research_questions=(
            ResearchQuestion(id="RQ1", question="Question?", objective_refs=()),
        ),
        information_needs=needs,
    )


def _source(*, content: str = "Exact excerpt in source.") -> Source:
    return Source(
        id="source-1",
        project_id="project-1",
        url="https://example.com",
        canonical_url="https://example.com",
        title="Title",
        retrieved_at="2026-01-01T00:00:00+00:00",
        retrieval_status=RetrievalStatus.ACQUIRED,
        content_text=content,
        workflow_run_refs=("run-obs",),
        research_design_refs=("design-1",),
        information_need_refs=("IN1",),
        metadata={
            "discovery_records": [
                {
                    "provider": "test",
                    "query_id": "sq-IN1",
                    "rank": 1,
                    "workflow_run_id": "run-obs",
                    "research_design_id": "design-1",
                },
            ],
        },
    )


def _run_context(*need_ids: str) -> RunScopedSourceContext:
    return RunScopedSourceContext(
        workflow_run_id="run-obs",
        research_design_id="design-1",
        information_need_ids=need_ids,
        research_question_ids=("RQ1",),
        query_ids=tuple(f"sq-{need_id}" for need_id in need_ids),
    )


def _workflow_context(design: ResearchDesign) -> WorkflowContext:
    template = WorkflowTemplate(
        id="tpl",
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
    run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
    run.id = "run-obs"
    context = WorkflowContext(
        project=Project(id="project-1", name="Project"),
        workflow_template=template,
        workflow_run=run,
    )
    context.current_task = run.tasks[0]
    return context


def _extractor_with_response(response: LLMResponse) -> LlmEvidenceExtractor:
    return LlmEvidenceExtractor(llm_client=Mock(generate=Mock(return_value=response)))


class SchemaContractMismatchFailClosedTests(unittest.TestCase):
    def _extract(self, content: str):
        return _extractor_with_response(
            LLMResponse(content=content, finish_reason="stop"),
        ).extract(
            source=_source(),
            design=_design("IN1"),
            run_context=_run_context("IN1"),
        )

    def test_1_missing_items_is_typed_fail_closed(self) -> None:
        with self.assertRaises(EvidenceResponseOutcomeError) as ctx:
            self._extract('{"evidence":[]}')
        self.assertEqual(
            ctx.exception.classification,
            EvidenceResponseClassification.SCHEMA_CONTRACT_MISMATCH.value,
        )
        shape = consume_response_shape()
        assert shape is not None
        self.assertEqual(
            shape.response_classification,
            EvidenceResponseClassification.SCHEMA_CONTRACT_MISMATCH.value,
        )

    def test_2_items_null_is_typed_fail_closed(self) -> None:
        with self.assertRaises(EvidenceResponseOutcomeError) as ctx:
            self._extract('{"items":null}')
        self.assertEqual(
            ctx.exception.classification,
            EvidenceResponseClassification.SCHEMA_CONTRACT_MISMATCH.value,
        )
        self.assertIsInstance(ctx.exception, EvidenceResponseOutcomeError)

    def test_3_items_wrong_scalar_and_object_type(self) -> None:
        for content in ('{"items":"foo"}', '{"items":{"statement":"x"}}', '{"items":1}'):
            with self.subTest(content=content):
                with self.assertRaises(EvidenceResponseOutcomeError) as ctx:
                    self._extract(content)
                self.assertEqual(
                    ctx.exception.classification,
                    EvidenceResponseClassification.SCHEMA_CONTRACT_MISMATCH.value,
                )

    def test_4_valid_empty_result_unchanged(self) -> None:
        candidates = self._extract('{"items":[]}')
        self.assertEqual(candidates, [])
        shape = consume_response_shape()
        assert shape is not None
        self.assertEqual(
            shape.response_classification,
            EvidenceResponseClassification.VALID_EMPTY_RESULT.value,
        )

    def test_5_valid_candidates_unchanged(self) -> None:
        payload = {
            "items": [
                {
                    "statement": "Market size is growing.",
                    "source_excerpt": "Exact excerpt in source.",
                    "information_need_id": "IN1",
                },
            ],
        }
        candidates = self._extract(json.dumps(payload))
        self.assertEqual(len(candidates), 1)
        shape = consume_response_shape()
        assert shape is not None
        self.assertEqual(
            shape.response_classification,
            EvidenceResponseClassification.VALID_CANDIDATES.value,
        )

    def test_6_classification_persists_on_exception_and_persister(self) -> None:
        source_repo = InMemorySourceRepository()
        source_repo.create(_source())
        executor = EvidenceExecutor(
            evidence_extraction_service=EvidenceExtractionService(
                evidence_extractor=ChunkedEvidenceExtractor(
                    _extractor_with_response(
                        LLMResponse(content='{"evidence":[]}', finish_reason="stop"),
                    ),
                ),
                evidence_repository=InMemoryEvidenceRepository(),
                source_repository=source_repo,
            ),
        )
        context = _workflow_context(_design("IN1"))
        with self.assertRaises(EvidenceExtractionError):
            executor.run(context)

        inner = context.shared_state["evidence_extraction"]["diagnostics"]["work_items"][0][
            "inner_chunks"
        ][0]
        self.assertEqual(
            inner["response_shape"]["response_classification"],
            EvidenceResponseClassification.SCHEMA_CONTRACT_MISMATCH.value,
        )
        self.assertEqual(inner["exception_class"], "EvidenceResponseOutcomeError")

        task = context.current_task
        assert task is not None
        task.ready()
        task.start()
        task.fail()
        persister = WorkflowRuntimePersister(
            workflow_service=mock.Mock(),
            audit=mock.Mock(),
            run_id=context.workflow_run.id,
        )
        persister.on_task_finished(context, error=EvidenceExtractionError("failed"))
        payload = extract_evidence_extraction(persister.task_results)
        assert payload is not None
        persisted = payload["diagnostics"]["work_items"][0]["inner_chunks"][0]["response_shape"]
        self.assertEqual(
            persisted["response_classification"],
            EvidenceResponseClassification.SCHEMA_CONTRACT_MISMATCH.value,
        )

    def test_7_aggregate_classification_counter(self) -> None:
        source_repo = InMemorySourceRepository()
        source_repo.create(_source())
        service = EvidenceExtractionService(
            evidence_extractor=ChunkedEvidenceExtractor(
                _extractor_with_response(
                    LLMResponse(content='{"items":null}', finish_reason="stop"),
                ),
            ),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=source_repo,
        )
        context = _workflow_context(_design("IN1"))
        summary = service.extract_for_source_ids(context, ("source-1",), allow_empty=True)
        diagnostics = summary.diagnostics
        assert diagnostics is not None
        counts = diagnostics.to_dict().get("response_classification_counts", {})
        self.assertEqual(counts.get("schema_contract_mismatch"), 1)
        self.assertNotIn("valid_empty_result", counts)


if __name__ == "__main__":
    unittest.main()

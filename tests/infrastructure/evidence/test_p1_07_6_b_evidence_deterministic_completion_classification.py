"""P1-07.6B deterministic Evidence response classification tests."""

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
from application.evidence.evidence_response_classification import (
    EvidenceResponseClassification,
    classify_evidence_llm_response,
)
from application.evidence.exceptions import EvidenceExtractionError, EvidenceResponseOutcomeError
from application.evidence.evidence_result_codec import extract_evidence_extraction
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.executors.evidence_executor import EvidenceExecutor
from application.runtime.workflow_runtime_persister import WorkflowRuntimePersister
from application.structured_output.json_extractor import JsonExtractor
from application.structured_output.json_validator import JsonValidator
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
    mock_client = Mock()
    mock_client.generate.return_value = response
    return LlmEvidenceExtractor(llm_client=mock_client)


def _valid_item_payload() -> dict:
    return {
        "items": [
            {
                "statement": "Market size is growing.",
                "source_excerpt": "Exact excerpt in source.",
                "information_need_id": "IN1",
            },
        ],
    }


def _extract_shape(response: LLMResponse, *, need_id: str = "IN1") -> dict:
    source_repo = InMemorySourceRepository()
    source_repo.create(_source())
    service = EvidenceExtractionService(
        evidence_extractor=ChunkedEvidenceExtractor(_extractor_with_response(response)),
        evidence_repository=InMemoryEvidenceRepository(),
        source_repository=source_repo,
    )
    context = _workflow_context(_design(need_id))
    summary = service.extract_for_source_ids(context, ("source-1",), allow_empty=True)
    diagnostics = summary.diagnostics
    assert diagnostics is not None
    inner = diagnostics.work_items[0].inner_chunks[0]
    assert inner.response_shape is not None
    return inner.response_shape.to_dict()


class EvidenceResponseClassificationPrecedenceTests(unittest.TestCase):
    def _classify(self, response: LLMResponse) -> EvidenceResponseClassification:
        classification, _ = classify_evidence_llm_response(
            response,
            json_extractor=JsonExtractor(),
            json_validator=JsonValidator(),
        )
        return classification

    def test_1_completed_empty_content(self) -> None:
        response = LLMResponse(content="", finish_reason="stop")
        self.assertEqual(
            self._classify(response),
            EvidenceResponseClassification.EMPTY_PROVIDER_OUTPUT,
        )

    def test_2_completed_whitespace_only_content(self) -> None:
        response = LLMResponse(content="   \n\t", finish_reason="stop")
        self.assertEqual(
            self._classify(response),
            EvidenceResponseClassification.INVALID_JSON,
        )

    def test_3_incomplete_empty_content(self) -> None:
        response = LLMResponse(
            content="",
            finish_reason="length",
            incomplete_reason="max_output_tokens",
        )
        self.assertEqual(
            self._classify(response),
            EvidenceResponseClassification.INCOMPLETE_PROVIDER_OUTPUT,
        )

    def test_4_incomplete_partial_json(self) -> None:
        response = LLMResponse(
            content='{"items":[{"statement":"partial",',
            finish_reason="length",
            incomplete_reason="max_output_tokens",
        )
        self.assertEqual(
            self._classify(response),
            EvidenceResponseClassification.INCOMPLETE_PROVIDER_OUTPUT,
        )

    def test_5_incomplete_valid_empty_items(self) -> None:
        response = LLMResponse(
            content='{"items":[]}',
            finish_reason="length",
            incomplete_reason="max_output_tokens",
        )
        self.assertEqual(
            self._classify(response),
            EvidenceResponseClassification.INCOMPLETE_PROVIDER_OUTPUT,
        )

    def test_6_incomplete_valid_candidates(self) -> None:
        response = LLMResponse(
            content=json.dumps(_valid_item_payload()),
            finish_reason="length",
            incomplete_reason="max_output_tokens",
        )
        self.assertEqual(
            self._classify(response),
            EvidenceResponseClassification.INCOMPLETE_PROVIDER_OUTPUT,
        )

    def test_7_completed_malformed_json(self) -> None:
        response = LLMResponse(
            content='{"items":[{"statement":"partial"',
            finish_reason="stop",
        )
        self.assertEqual(
            self._classify(response),
            EvidenceResponseClassification.INVALID_JSON,
        )

    def test_8_completed_root_array(self) -> None:
        response = LLMResponse(content="[]", finish_reason="stop")
        self.assertEqual(
            self._classify(response),
            EvidenceResponseClassification.ROOT_TYPE_MISMATCH,
        )

    def test_9_completed_root_string(self) -> None:
        response = LLMResponse(content=json.dumps("foo"), finish_reason="stop")
        self.assertEqual(
            self._classify(response),
            EvidenceResponseClassification.ROOT_TYPE_MISMATCH,
        )

    def test_10_completed_root_null(self) -> None:
        response = LLMResponse(content="null", finish_reason="stop")
        self.assertEqual(
            self._classify(response),
            EvidenceResponseClassification.ROOT_TYPE_MISMATCH,
        )

    def test_10b_completed_root_number_and_boolean(self) -> None:
        self.assertEqual(
            self._classify(LLMResponse(content="123", finish_reason="stop")),
            EvidenceResponseClassification.ROOT_TYPE_MISMATCH,
        )
        self.assertEqual(
            self._classify(LLMResponse(content="true", finish_reason="stop")),
            EvidenceResponseClassification.ROOT_TYPE_MISMATCH,
        )

    def test_11_completed_object_missing_items(self) -> None:
        response = LLMResponse(content='{"evidence":[]}', finish_reason="stop")
        self.assertEqual(
            self._classify(response),
            EvidenceResponseClassification.SCHEMA_CONTRACT_MISMATCH,
        )

    def test_12_completed_items_wrong_type(self) -> None:
        response = LLMResponse(content='{"items":"not-a-list"}', finish_reason="stop")
        self.assertEqual(
            self._classify(response),
            EvidenceResponseClassification.SCHEMA_CONTRACT_MISMATCH,
        )

    def test_13_completed_valid_empty_items(self) -> None:
        response = LLMResponse(content='{"items":[]}', finish_reason="stop")
        self.assertEqual(
            self._classify(response),
            EvidenceResponseClassification.VALID_EMPTY_RESULT,
        )

    def test_14_completed_valid_candidates(self) -> None:
        response = LLMResponse(
            content=json.dumps(_valid_item_payload()),
            finish_reason="stop",
        )
        self.assertEqual(
            self._classify(response),
            EvidenceResponseClassification.VALID_CANDIDATES,
        )

    def test_16_unknown_completion_metadata_valid_payload(self) -> None:
        response = LLMResponse(content='{"items":[]}')
        self.assertEqual(
            self._classify(response),
            EvidenceResponseClassification.VALID_EMPTY_RESULT,
        )


class LlmEvidenceExtractorClassificationBehaviorTests(unittest.TestCase):
    def test_empty_provider_output_raises_typed_outcome(self) -> None:
        extractor = _extractor_with_response(LLMResponse(content="", finish_reason="stop"))
        with self.assertRaises(EvidenceResponseOutcomeError) as ctx:
            extractor.extract(
                source=_source(),
                design=_design("IN1"),
                run_context=_run_context("IN1"),
            )
        self.assertEqual(
            ctx.exception.classification,
            EvidenceResponseClassification.EMPTY_PROVIDER_OUTPUT.value,
        )

    def test_incomplete_raises_before_json_parse(self) -> None:
        extractor = _extractor_with_response(
            LLMResponse(
                content='{"items":[]}',
                finish_reason="length",
                incomplete_reason="max_output_tokens",
            ),
        )
        with self.assertRaises(EvidenceResponseOutcomeError) as ctx:
            extractor.extract(
                source=_source(),
                design=_design("IN1"),
                run_context=_run_context("IN1"),
            )
        self.assertEqual(
            ctx.exception.classification,
            EvidenceResponseClassification.INCOMPLETE_PROVIDER_OUTPUT.value,
        )

    def test_valid_empty_result_returns_zero_candidates(self) -> None:
        extractor = _extractor_with_response(
            LLMResponse(content='{"items":[]}', finish_reason="stop"),
        )
        candidates = extractor.extract(
            source=_source(),
            design=_design("IN1"),
            run_context=_run_context("IN1"),
        )
        self.assertEqual(candidates, [])
        shape = consume_response_shape()
        assert shape is not None
        self.assertEqual(
            shape.response_classification,
            EvidenceResponseClassification.VALID_EMPTY_RESULT.value,
        )

    def test_schema_missing_items_is_fail_closed(self) -> None:
        extractor = _extractor_with_response(
            LLMResponse(content='{"evidence":[]}', finish_reason="stop"),
        )
        with self.assertRaises(EvidenceResponseOutcomeError) as ctx:
            extractor.extract(
                source=_source(),
                design=_design("IN1"),
                run_context=_run_context("IN1"),
            )
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

    def test_items_null_is_fail_closed(self) -> None:
        extractor = _extractor_with_response(
            LLMResponse(content='{"items":null}', finish_reason="stop"),
        )
        with self.assertRaises(EvidenceResponseOutcomeError) as ctx:
            extractor.extract(
                source=_source(),
                design=_design("IN1"),
                run_context=_run_context("IN1"),
            )
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


class ClassificationPersistenceTests(unittest.TestCase):
    def test_17_classification_survives_exception_observation(self) -> None:
        shape = _extract_shape(
            LLMResponse(content="", finish_reason="stop"),
        )
        self.assertEqual(
            shape["response_classification"],
            EvidenceResponseClassification.EMPTY_PROVIDER_OUTPUT.value,
        )
        self.assertIn("completion_finish_reason", shape)

    def test_18_classification_survives_workflow_runtime_persister(self) -> None:
        source_repo = InMemorySourceRepository()
        source_repo.create(_source())
        response = LLMResponse(
            content='{"items":[{"statement":"partial",',
            finish_reason="length",
            incomplete_reason="max_output_tokens",
            output_tokens=4096,
        )
        executor = EvidenceExecutor(
            evidence_extraction_service=EvidenceExtractionService(
                evidence_extractor=ChunkedEvidenceExtractor(
                    _extractor_with_response(response),
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
            EvidenceResponseClassification.INCOMPLETE_PROVIDER_OUTPUT.value,
        )

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
            EvidenceResponseClassification.INCOMPLETE_PROVIDER_OUTPUT.value,
        )

    def test_aggregate_response_classification_counts(self) -> None:
        source_repo = InMemorySourceRepository()
        calls = {"n": 0}

        def _generate(_prompt):
            calls["n"] += 1
            if calls["n"] == 1:
                return LLMResponse(content='{"items":[]}', finish_reason="stop")
            return LLMResponse(content="", finish_reason="stop")

        extractor = LlmEvidenceExtractor(llm_client=Mock(generate=_generate))
        long_source = _source(content=("Exact excerpt in source. " * 500))
        source_repo.create(long_source)
        service = EvidenceExtractionService(
            evidence_extractor=ChunkedEvidenceExtractor(extractor, chunk_chars=200, overlap_chars=0),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=source_repo,
        )
        context = _workflow_context(_design("IN1"))
        summary = service.extract_for_source_ids(context, (long_source.id,), allow_empty=True)
        diagnostics = summary.diagnostics
        assert diagnostics is not None
        counts = diagnostics.to_dict().get("response_classification_counts", {})
        self.assertGreaterEqual(counts.get("valid_empty_result", 0), 1)
        self.assertGreaterEqual(counts.get("empty_provider_output", 0), 1)


class GroundingDoesNotChangeClassificationTests(unittest.TestCase):
    def test_15_grounding_rejection_keeps_valid_candidates_classification(self) -> None:
        payload = {
            "items": [
                {
                    "statement": "Market size is growing.",
                    "source_excerpt": "This text is not in the source.",
                    "information_need_id": "IN1",
                },
            ],
        }
        shape = _extract_shape(
            LLMResponse(content=json.dumps(payload), finish_reason="stop"),
        )
        self.assertEqual(
            shape["response_classification"],
            EvidenceResponseClassification.VALID_CANDIDATES.value,
        )


if __name__ == "__main__":
    unittest.main()

"""P1-07.6A completion metadata observability tests for Evidence extraction."""

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
from application.evidence.evidence_extractor_response_shape import (
    ResponseShapeDiagnostics,
    consume_response_shape,
)
from application.structured_output.json_extractor import JsonExtractor
from application.structured_output.json_validator import JsonValidator
from application.evidence.exceptions import EvidenceExtractionError
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
    mock_client = Mock()
    mock_client.generate.return_value = response
    return LlmEvidenceExtractor(llm_client=mock_client)


def _extract_with_chunked(response: LLMResponse, *, need_id: str = "IN1") -> dict:
    source_repo = InMemorySourceRepository()
    source_repo.create(_source())
    extractor = _extractor_with_response(response)
    service = EvidenceExtractionService(
        evidence_extractor=ChunkedEvidenceExtractor(extractor),
        evidence_repository=InMemoryEvidenceRepository(),
        source_repository=source_repo,
    )
    context = _workflow_context(_design(need_id))
    summary = service.extract_for_source_ids(context, ("source-1",), allow_empty=True)
    diagnostics = summary.diagnostics
    assert diagnostics is not None
    assert diagnostics.work_items
    inner_chunk = diagnostics.work_items[0].inner_chunks[0]
    assert inner_chunk.response_shape is not None
    return inner_chunk.response_shape.to_dict()

class CompletionMetadataCaptureTests(unittest.TestCase):
    def test_a_completed_valid_json_with_candidates(self) -> None:
        payload = {
            "items": [
                {
                    "statement": "Market size is growing.",
                    "source_excerpt": "Exact excerpt in source.",
                    "information_need_id": "IN1",
                },
            ],
        }
        response = LLMResponse(
            content=json.dumps(payload),
            finish_reason="stop",
            output_tokens=120,
            reasoning_tokens=40,
            max_output_tokens=4096,
        )
        shape = _extract_with_chunked(response)
        self.assertEqual(shape["completion_finish_reason"], "stop")
        self.assertIsNone(shape["completion_incomplete_reason"])
        self.assertFalse(shape["completion_was_truncated"])
        self.assertEqual(shape["completion_output_tokens"], 120)
        self.assertEqual(shape["completion_reasoning_tokens"], 40)
        self.assertEqual(shape["completion_max_output_tokens"], 4096)
        self.assertEqual(shape["items_count_post_filter"], 1)

    def test_b_completed_empty_items(self) -> None:
        response = LLMResponse(content='{"items":[]}', finish_reason="stop")
        shape = _extract_with_chunked(response)
        self.assertEqual(shape["completion_finish_reason"], "stop")
        self.assertFalse(shape["completion_was_truncated"])
        self.assertEqual(shape["items_count_post_filter"], 0)

    def test_c_incomplete_partial_json_preserves_metadata_on_exception(self) -> None:
        content = '{"items":[{"statement":"partial",'
        response = LLMResponse(
            content=content,
            finish_reason="length",
            incomplete_reason="max_output_tokens",
            output_tokens=4096,
            max_output_tokens=4096,
            reasoning_tokens=3500,
        )
        extractor = _extractor_with_response(response)
        with self.assertRaises(ValueError):
            extractor.extract(
                source=_source(),
                design=_design("IN1"),
                run_context=_run_context("IN1"),
            )
        shape = consume_response_shape()
        assert shape is not None
        shape_dict = shape.to_dict()
        self.assertEqual(shape_dict["completion_finish_reason"], "length")
        self.assertEqual(shape_dict["completion_incomplete_reason"], "max_output_tokens")
        self.assertTrue(shape_dict["completion_was_truncated"])
        self.assertEqual(shape_dict["response_text_length"], len(content))
        self.assertEqual(shape_dict["parsed_root_type"], "no_valid_json")

    def test_d_incomplete_empty_content(self) -> None:
        response = LLMResponse(
            content="",
            finish_reason="length",
            incomplete_reason="max_output_tokens",
            output_tokens=4096,
            max_output_tokens=4096,
            reasoning_tokens=4096,
        )
        extractor = _extractor_with_response(response)
        with self.assertRaises(ValueError):
            extractor.extract(
                source=_source(),
                design=_design("IN1"),
                run_context=_run_context("IN1"),
            )
        shape = consume_response_shape()
        assert shape is not None
        shape_dict = shape.to_dict()
        self.assertEqual(shape_dict["response_text_length"], 0)
        self.assertTrue(shape_dict["completion_was_truncated"])
        self.assertEqual(shape_dict["completion_incomplete_reason"], "max_output_tokens")

    def test_e_completed_malformed_json_not_marked_truncated(self) -> None:
        content = '{"items":[{"statement":"partial"'
        response = LLMResponse(content=content, finish_reason="stop")
        extractor = _extractor_with_response(response)
        with self.assertRaises(ValueError):
            extractor.extract(
                source=_source(),
                design=_design("IN1"),
                run_context=_run_context("IN1"),
            )
        shape = consume_response_shape()
        assert shape is not None
        shape_dict = shape.to_dict()
        self.assertEqual(shape_dict["completion_finish_reason"], "stop")
        self.assertFalse(shape_dict["completion_was_truncated"])
        self.assertIsNone(shape_dict["completion_incomplete_reason"])

    def test_e_completed_wrong_root_type(self) -> None:
        response = LLMResponse(content="[]", finish_reason="stop")
        extractor = _extractor_with_response(response)
        with self.assertRaises(ValueError):
            extractor.extract(
                source=_source(),
                design=_design("IN1"),
                run_context=_run_context("IN1"),
            )
        shape = consume_response_shape()
        assert shape is not None
        self.assertEqual(shape.completion_finish_reason, "stop")
        self.assertFalse(shape.completion_was_truncated)

    def test_f_missing_token_metadata_null_safe(self) -> None:
        response = LLMResponse(content='{"items":[]}', finish_reason="stop")
        shape = _extract_with_chunked(response)
        self.assertIsNone(shape["completion_output_tokens"])
        self.assertIsNone(shape["completion_reasoning_tokens"])
        self.assertIsNone(shape["completion_max_output_tokens"])
        self.assertIsNone(shape["completion_configured_reasoning_effort"])

    def test_g_reasoning_and_output_token_values_persist(self) -> None:
        response = LLMResponse(
            content='{"items":[]}',
            finish_reason="stop",
            output_tokens=512,
            reasoning_tokens=128,
            max_output_tokens=4096,
            configured_reasoning_effort="minimal",
        )
        shape = _extract_with_chunked(response)
        self.assertEqual(shape["completion_output_tokens"], 512)
        self.assertEqual(shape["completion_reasoning_tokens"], 128)
        self.assertEqual(shape["completion_max_output_tokens"], 4096)
        self.assertEqual(shape["completion_configured_reasoning_effort"], "minimal")

    def test_g_empty_content_with_no_incomplete_reason(self) -> None:
        response = LLMResponse(content="", finish_reason="stop")
        extractor = _extractor_with_response(response)
        with self.assertRaises(ValueError):
            extractor.extract(
                source=_source(),
                design=_design("IN1"),
                run_context=_run_context("IN1"),
            )
        shape = consume_response_shape()
        assert shape is not None
        self.assertEqual(shape.completion_finish_reason, "stop")
        self.assertIsNone(shape.completion_incomplete_reason)
        self.assertFalse(shape.completion_was_truncated)


class ProviderNeutralBoundaryTests(unittest.TestCase):
    def test_i_uses_llm_response_only_at_evidence_level(self) -> None:
        response = LLMResponse(
            content='{"items":[]}',
            finish_reason="stop",
            incomplete_reason=None,
            output_tokens=10,
        )
        diagnostics = ResponseShapeDiagnostics.from_llm_response(
            response,
            json_extractor=JsonExtractor(),
            json_validator=JsonValidator(),
        )
        self.assertEqual(diagnostics.completion_finish_reason, "stop")
        self.assertIsNone(diagnostics.completion_incomplete_reason)


class VisibleOutputLengthTests(unittest.TestCase):
    def test_response_text_length_is_visible_output_length(self) -> None:
        content = '{"items":[]}'
        response = LLMResponse(content=content, finish_reason="stop")
        diagnostics = ResponseShapeDiagnostics.from_llm_response(
            response,
            json_extractor=JsonExtractor(),
            json_validator=JsonValidator(),
        )
        self.assertEqual(diagnostics.response_text_length, response.visible_output_length)
        shape_dict = diagnostics.to_dict()
        self.assertNotIn("visible_output_length", shape_dict)


class BackwardCompatibilityTests(unittest.TestCase):
    def test_existing_p1_07_4_1_fields_remain(self) -> None:
        response = LLMResponse(content='{"items":[]}', finish_reason="stop")
        shape = _extract_with_chunked(response)
        for key in (
            "provider_response_received",
            "response_text_length",
            "response_preview",
            "response_preview_truncated",
            "json_container_count",
            "container_root_types",
            "parsed_root_type",
            "expected_items_key_present",
            "items_value_type",
            "items_count_pre_filter",
            "items_count_post_filter",
            "parser_succeeded",
        ):
            self.assertIn(key, shape)


class CompletionMetadataPersistenceTests(unittest.TestCase):
    def test_h_metadata_survives_workflow_runtime_persister(self) -> None:
        source_repo = InMemorySourceRepository()
        source_repo.create(_source())
        response = LLMResponse(
            content='{"items":[{"statement":"partial",',
            finish_reason="length",
            incomplete_reason="max_output_tokens",
            output_tokens=4096,
            reasoning_tokens=3200,
            max_output_tokens=4096,
        )
        extractor = LlmEvidenceExtractor(
            llm_client=Mock(generate=Mock(return_value=response)),
        )
        executor = EvidenceExecutor(
            evidence_extraction_service=EvidenceExtractionService(
                evidence_extractor=ChunkedEvidenceExtractor(extractor),
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
        shape = inner["response_shape"]
        self.assertEqual(inner["extractor_status"], "exception")
        self.assertEqual(shape["completion_finish_reason"], "length")
        self.assertEqual(shape["completion_incomplete_reason"], "max_output_tokens")
        self.assertTrue(shape["completion_was_truncated"])
        self.assertEqual(shape["completion_output_tokens"], 4096)
        self.assertEqual(shape["completion_reasoning_tokens"], 3200)

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
        self.assertEqual(persisted["completion_finish_reason"], "length")
        self.assertTrue(persisted["completion_was_truncated"])


if __name__ == "__main__":
    unittest.main()

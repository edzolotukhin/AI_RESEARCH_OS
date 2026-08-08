"""P1-07.4.1 response-shape observability tests for LlmEvidenceExtractor."""

from __future__ import annotations

import json
import unittest
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
    DEFAULT_RESPONSE_PREVIEW_MAX_LENGTH,
    build_bounded_response_preview,
)
from application.evidence.exceptions import EvidenceExtractionError
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.executors.evidence_executor import EvidenceExecutor
from application.runtime.workflow_runtime_persister import WorkflowRuntimePersister
from application.evidence.evidence_result_codec import extract_evidence_extraction
from infrastructure.evidence.llm_evidence_extractor import LlmEvidenceExtractor
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)
from runtime.workflow_context import WorkflowContext
from unittest import mock


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


def _extractor_with_content(content: str) -> LlmEvidenceExtractor:
    mock_client = Mock()
    mock_client.generate.return_value = LLMResponse(content=content)
    return LlmEvidenceExtractor(llm_client=mock_client)


def _extract_with_chunked(content: str, *, need_id: str = "IN1") -> dict:
    source_repo = InMemorySourceRepository()
    source_repo.create(_source())
    extractor = _extractor_with_content(content)
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


class ResponsePreviewTests(unittest.TestCase):
    def test_oversized_response_preview_is_truncated(self) -> None:
        content = "x" * (DEFAULT_RESPONSE_PREVIEW_MAX_LENGTH + 100)
        preview, truncated = build_bounded_response_preview(content)
        self.assertTrue(truncated)
        self.assertLessEqual(len(preview), DEFAULT_RESPONSE_PREVIEW_MAX_LENGTH + 1)
        self.assertTrue(preview.endswith("…"))


class LlmEvidenceExtractorResponseShapeTests(unittest.TestCase):
    def _extract(self, content: str, *, need_id: str = "IN1") -> list:
        extractor = _extractor_with_content(content)
        return extractor.extract(
            source=_source(),
            design=_design(need_id),
            run_context=_run_context(need_id),
        )

    def test_a_valid_object_with_one_item(self) -> None:
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
        shape = _extract_with_chunked(json.dumps(payload))
        self.assertEqual(shape["parsed_root_type"], "object")
        self.assertTrue(shape["expected_items_key_present"])
        self.assertEqual(shape["items_value_type"], "array")
        self.assertEqual(shape["items_count_pre_filter"], 1)
        self.assertEqual(shape["items_count_post_filter"], 1)

    def test_b_valid_object_with_empty_items(self) -> None:
        self._extract(json.dumps({"items": []}))
        shape = _extract_with_chunked(json.dumps({"items": []}))
        self.assertEqual(shape["items_count_pre_filter"], 0)
        self.assertEqual(shape["items_count_post_filter"], 0)

    def test_c_evidence_alias_key_absent_items(self) -> None:
        payload = {
            "evidence": [
                {
                    "statement": "Market size is growing.",
                    "source_excerpt": "Exact excerpt in source.",
                    "information_need_id": "IN1",
                },
            ],
        }
        self.assertEqual(self._extract(json.dumps(payload)), [])
        shape = _extract_with_chunked(json.dumps(payload))
        self.assertIn("evidence", shape["parsed_root_keys"])
        self.assertFalse(shape["expected_items_key_present"])
        self.assertEqual(shape["items_value_type"], "missing")
        self.assertEqual(shape["items_count_post_filter"], 0)

    def test_d_nested_wrapper_missing_items(self) -> None:
        payload = {
            "result": {
                "items": [
                    {
                        "statement": "Market size is growing.",
                        "source_excerpt": "Exact excerpt in source.",
                        "information_need_id": "IN1",
                    },
                ],
            },
        }
        self.assertEqual(self._extract(json.dumps(payload)), [])
        shape = _extract_with_chunked(json.dumps(payload))
        self.assertIn("result", shape["parsed_root_keys"])
        self.assertFalse(shape["expected_items_key_present"])

    def test_e_root_array_value_error_with_preview(self) -> None:
        payload = [{"statement": "x", "source_excerpt": "y", "information_need_id": "IN1"}]
        with self.assertRaises(ValueError):
            self._extract(json.dumps(payload))
        shape = _extract_with_chunked(json.dumps(payload))
        self.assertEqual(shape["parsed_root_type"], "array")
        self.assertTrue(shape["provider_response_received"])
        self.assertIn("[", shape["response_preview"])

    def test_f_root_string_and_null_types(self) -> None:
        with self.assertRaises(ValueError):
            self._extract(json.dumps("no evidence"))
        shape = _extract_with_chunked(json.dumps("no evidence"))
        self.assertEqual(shape["parsed_root_type"], "string")

        with self.assertRaises(ValueError):
            self._extract("null")
        shape = _extract_with_chunked("null")
        self.assertEqual(shape["parsed_root_type"], "null")

        with self.assertRaises(ValueError):
            self._extract("42")
        shape = _extract_with_chunked("42")
        self.assertEqual(shape["parsed_root_type"], "number")

    def test_g_missing_need_id_rejection(self) -> None:
        payload = {
            "items": [
                {
                    "statement": "Market size is growing.",
                    "source_excerpt": "Exact excerpt in source.",
                },
            ],
        }
        self.assertEqual(self._extract(json.dumps(payload)), [])
        shape = _extract_with_chunked(json.dumps(payload))
        self.assertEqual(shape["rejected_missing_information_need_id"], 1)

    def test_h_unknown_need_id_rejection(self) -> None:
        payload = {
            "items": [
                {
                    "statement": "Market size is growing.",
                    "source_excerpt": "Exact excerpt in source.",
                    "information_need_id": "UNKNOWN",
                },
            ],
        }
        shape = _extract_with_chunked(json.dumps(payload))
        self.assertEqual(shape["rejected_unknown_information_need_id"], 1)

    def test_i_empty_statement_rejection(self) -> None:
        payload = {
            "items": [
                {
                    "statement": "",
                    "source_excerpt": "Exact excerpt in source.",
                    "information_need_id": "IN1",
                },
            ],
        }
        shape = _extract_with_chunked(json.dumps(payload))
        self.assertEqual(shape["rejected_empty_statement"], 1)

    def test_j_empty_excerpt_rejection(self) -> None:
        payload = {
            "items": [
                {
                    "statement": "Market size is growing.",
                    "source_excerpt": "",
                    "information_need_id": "IN1",
                },
            ],
        }
        shape = _extract_with_chunked(json.dumps(payload))
        self.assertEqual(shape["rejected_empty_source_excerpt"], 1)

    def test_k_non_dict_item_rejection(self) -> None:
        payload = {"items": ["not-an-object"]}
        shape = _extract_with_chunked(json.dumps(payload))
        self.assertEqual(shape["rejected_non_object_item"], 1)

    def test_l_invalid_confidence_preserves_exception(self) -> None:
        payload = {
            "items": [
                {
                    "statement": "Market size is growing.",
                    "source_excerpt": "Exact excerpt in source.",
                    "information_need_id": "IN1",
                    "confidence": "not-a-number",
                },
            ],
        }
        with self.assertRaises(ValueError):
            self._extract(json.dumps(payload))

    def test_m_multiple_json_containers(self) -> None:
        object_payload = {
            "items": [
                {
                    "statement": "Market size is growing.",
                    "source_excerpt": "Exact excerpt in source.",
                    "information_need_id": "IN1",
                },
            ],
        }
        content = json.dumps([]) + "\n" + json.dumps(object_payload)
        shape = _extract_with_chunked(content)
        self.assertEqual(shape["json_container_count"], 2)
        self.assertEqual(shape["container_root_types"], ["array", "object"])
        self.assertEqual(shape["items_count_post_filter"], 1)


class FailurePathResponseShapePersistenceTests(unittest.TestCase):
    def test_o_failure_path_persists_response_shape(self) -> None:
        source_repo = InMemorySourceRepository()
        source_repo.create(_source())
        extractor = LlmEvidenceExtractor(
            llm_client=Mock(
                generate=Mock(return_value=LLMResponse(content='{"evidence":[]}')),
            ),
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

        diagnostics = context.shared_state["evidence_extraction"]["diagnostics"]
        inner = diagnostics["work_items"][0]["inner_chunks"][0]
        self.assertIn("response_shape", inner)
        shape = inner["response_shape"]
        self.assertIn("evidence", shape["parsed_root_keys"])
        self.assertFalse(shape["expected_items_key_present"])
        self.assertGreater(diagnostics["inner_calls_zero_candidates"], 0)

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
        persisted_inner = payload["diagnostics"]["work_items"][0]["inner_chunks"][0]
        self.assertIn("response_shape", persisted_inner)


if __name__ == "__main__":
    unittest.main()

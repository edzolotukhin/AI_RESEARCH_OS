"""P1-07.4 offline forensic tests for LlmEvidenceExtractor contract boundary."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from domain.ai.llm_response import LLMResponse
from domain.evidence.evidence_type import EvidenceType
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source

from application.evidence.exceptions import EvidenceResponseOutcomeError
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from infrastructure.evidence.llm_evidence_extractor import LlmEvidenceExtractor


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
    )


def _run_context(*need_ids: str) -> RunScopedSourceContext:
    return RunScopedSourceContext(
        workflow_run_id="run-1",
        research_design_id="design-1",
        information_need_ids=need_ids,
        research_question_ids=("RQ1",),
        query_ids=tuple(f"sq-{need_id}" for need_id in need_ids),
    )


def _extractor_with_content(content: str) -> LlmEvidenceExtractor:
    mock_client = Mock()
    mock_client.generate.return_value = LLMResponse(content=content)
    return LlmEvidenceExtractor(llm_client=mock_client)


class LlmEvidenceExtractorContractForensicsTests(unittest.TestCase):
    def _extract(self, content: str, *, need_id: str = "IN1") -> list:
        extractor = _extractor_with_content(content)
        return extractor.extract(
            source=_source(content="Exact excerpt in source."),
            design=_design(need_id),
            run_context=_run_context(need_id),
        )

    def test_valid_object_with_one_item_returns_one_candidate(self) -> None:
        payload = {
            "items": [
                {
                    "statement": "Market size is growing.",
                    "source_excerpt": "Exact excerpt in source.",
                    "information_need_id": "IN1",
                    "evidence_type": "direct_excerpt",
                },
            ],
        }
        candidates = self._extract(json.dumps(payload))
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].information_need_refs, ("IN1",))

    def test_valid_object_with_empty_items_returns_zero_candidates(self) -> None:
        candidates = self._extract(json.dumps({"items": []}))
        self.assertEqual(candidates, [])

    def test_root_json_array_raises_value_error(self) -> None:
        payload = [
            {
                "statement": "Market size is growing.",
                "source_excerpt": "Exact excerpt in source.",
                "information_need_id": "IN1",
            },
        ]
        with self.assertRaises(ValueError) as ctx:
            self._extract(json.dumps(payload))
        self.assertIn("must be a JSON object", str(ctx.exception))

    def test_root_json_string_raises_value_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._extract(json.dumps("no evidence here"))
        self.assertIn("must be a JSON object", str(ctx.exception))

    def test_root_null_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            self._extract("null")

    def test_missing_items_field_is_schema_contract_mismatch(self) -> None:
        with self.assertRaises(EvidenceResponseOutcomeError) as ctx:
            self._extract(json.dumps({"evidence": []}))
        self.assertEqual(ctx.exception.classification, "schema_contract_mismatch")

    def test_alternative_evidence_field_with_items_is_schema_contract_mismatch(self) -> None:
        payload = {
            "evidence": [
                {
                    "statement": "Market size is growing.",
                    "source_excerpt": "Exact excerpt in source.",
                    "information_need_id": "IN1",
                },
            ],
        }
        with self.assertRaises(EvidenceResponseOutcomeError) as ctx:
            self._extract(json.dumps(payload))
        self.assertEqual(ctx.exception.classification, "schema_contract_mismatch")

    def test_wrapped_object_without_top_level_items_is_schema_contract_mismatch(self) -> None:
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
        with self.assertRaises(EvidenceResponseOutcomeError) as ctx:
            self._extract(json.dumps(payload))
        self.assertEqual(ctx.exception.classification, "schema_contract_mismatch")

    def test_malformed_items_are_silently_skipped(self) -> None:
        payload = {
            "items": [
                "not-an-object",
                {
                    "statement": "",
                    "source_excerpt": "Exact excerpt in source.",
                    "information_need_id": "IN1",
                },
                {
                    "statement": "Valid",
                    "source_excerpt": "Exact excerpt in source.",
                    "information_need_id": "WRONG",
                },
            ],
        }
        candidates = self._extract(json.dumps(payload))
        self.assertEqual(candidates, [])

    def test_items_null_is_schema_contract_mismatch(self) -> None:
        with self.assertRaises(EvidenceResponseOutcomeError) as ctx:
            self._extract(json.dumps({"items": None}))
        self.assertEqual(ctx.exception.classification, "schema_contract_mismatch")

    def test_truncated_json_raises_value_error(self) -> None:
        truncated = '{"items":[{"statement":"partial'
        with self.assertRaises(ValueError):
            self._extract(truncated)

    def test_markdown_fenced_object_is_parsed(self) -> None:
        payload = {
            "items": [
                {
                    "statement": "Market size is growing.",
                    "source_excerpt": "Exact excerpt in source.",
                    "information_need_id": "IN1",
                },
            ],
        }
        content = f"Here is the result:\n```json\n{json.dumps(payload)}\n```"
        candidates = self._extract(content)
        self.assertEqual(len(candidates), 1)

    def test_multiple_root_json_values_use_first_object(self) -> None:
        """Parser scans all root JSON values and returns the first object."""
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
        candidates = self._extract(content)
        self.assertEqual(len(candidates), 1)

    def test_parse_payload_direct_matrix(self) -> None:
        extractor = _extractor_with_content("")
        cases = {
            "object": ('{"items":[]}', dict),
            "array": ("[]", ValueError),
            "string": ('"x"', ValueError),
            "null": ("null", ValueError),
            "number": ("42", ValueError),
        }
        for name, (content, expected) in cases.items():
            with self.subTest(shape=name):
                if expected is ValueError:
                    with self.assertRaises(ValueError):
                        extractor._parse_payload(content)
                else:
                    result = extractor._parse_payload(content)
                    self.assertIsInstance(result, expected)


class ExtractorCounterSemanticsForensicsTests(unittest.TestCase):
    """Document run-level vs inner-chunk success semantics via integration."""

    def test_inner_success_zero_candidates_does_not_increment_run_successes(self) -> None:
        from application.evidence.evidence_extraction_service import EvidenceExtractionService
        from application.evidence.chunked_evidence_extractor import ChunkedEvidenceExtractor
        from application.ports.evidence_ports import EvidenceCandidate, EvidenceExtractor
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

        class _EmptyInner(EvidenceExtractor):
            method_name = "empty"

            def extract(self, *, source, design, run_context):
                return []

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
            research_design_snapshot=_design("IN1"),
        )
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
        run.id = "run-1"
        context = WorkflowContext(
            project=Project(id="project-1", name="Project"),
            workflow_template=template,
            workflow_run=run,
        )
        source = _source()
        source.workflow_run_refs = ("run-1",)
        source.information_need_refs = ("IN1",)
        source.research_design_refs = ("design-1",)
        source.metadata = {
            "discovery_records": [
                {
                    "provider": "test",
                    "query_id": "sq-IN1",
                    "rank": 1,
                    "workflow_run_id": "run-1",
                    "research_design_id": "design-1",
                },
            ],
        }
        source.retrieval_status = RetrievalStatus.ACQUIRED
        source_repo = InMemorySourceRepository()
        source_repo.create(source)
        service = EvidenceExtractionService(
            evidence_extractor=ChunkedEvidenceExtractor(_EmptyInner()),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=source_repo,
        )
        context.current_task = run.tasks[0]

        class _CapturingService(EvidenceExtractionService):
            def _extract_work_queue(self, queue, **kwargs):
                kwargs["allow_empty_failure"] = False
                return super()._extract_work_queue(queue, **kwargs)

        summary = _CapturingService(
            evidence_extractor=service._evidence_extractor,
            evidence_repository=service._evidence_repository,
            source_repository=service._source_repository,
        ).extract_for_context(context)

        diagnostics = summary.diagnostics
        assert diagnostics is not None
        self.assertEqual(diagnostics.extractor_attempts, 1)
        self.assertEqual(diagnostics.extractor_successes, 0)
        self.assertEqual(diagnostics.extractor_failures, 0)
        self.assertEqual(diagnostics.work_items[0].inner_chunks[0].extractor_status, "success")
        self.assertEqual(diagnostics.work_items[0].extractor_status, "no_candidates")

    def test_inner_value_error_does_not_increment_run_failures(self) -> None:
        from application.evidence.chunked_evidence_extractor import ChunkedEvidenceExtractor
        from application.evidence.evidence_extraction_service import EvidenceExtractionService
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
            research_design_snapshot=_design("IN1"),
        )
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
        run.id = "run-1"
        context = WorkflowContext(
            project=Project(id="project-1", name="Project"),
            workflow_template=template,
            workflow_run=run,
        )
        source = _source()
        source.workflow_run_refs = ("run-1",)
        source.information_need_refs = ("IN1",)
        source.research_design_refs = ("design-1",)
        source.metadata = {
            "discovery_records": [
                {
                    "provider": "test",
                    "query_id": "sq-IN1",
                    "rank": 1,
                    "workflow_run_id": "run-1",
                    "research_design_id": "design-1",
                },
            ],
        }
        source.retrieval_status = RetrievalStatus.ACQUIRED
        source_repo = InMemorySourceRepository()
        source_repo.create(source)

        extractor = LlmEvidenceExtractor(
            llm_client=Mock(
                generate=Mock(
                    return_value=LLMResponse(content="[]"),
                ),
            ),
        )
        service = EvidenceExtractionService(
            evidence_extractor=ChunkedEvidenceExtractor(extractor),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=source_repo,
        )
        context.current_task = run.tasks[0]

        class _CapturingService(EvidenceExtractionService):
            def _extract_work_queue(self, queue, **kwargs):
                kwargs["allow_empty_failure"] = False
                return super()._extract_work_queue(queue, **kwargs)

        summary = _CapturingService(
            evidence_extractor=service._evidence_extractor,
            evidence_repository=service._evidence_repository,
            source_repository=service._source_repository,
        ).extract_for_context(context)

        diagnostics = summary.diagnostics
        assert diagnostics is not None
        self.assertEqual(diagnostics.extractor_failures, 0)
        self.assertEqual(
            diagnostics.work_items[0].inner_chunks[0].exception_message,
            "LLM evidence payload must be a JSON object",
        )
        self.assertEqual(diagnostics.work_items[0].extractor_status, "no_candidates")


if __name__ == "__main__":
    unittest.main()

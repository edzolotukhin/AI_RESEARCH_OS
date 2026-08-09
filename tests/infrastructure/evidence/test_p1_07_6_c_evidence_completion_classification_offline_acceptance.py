"""P1-07.6C offline acceptance for Evidence completion classification."""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path
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

from dataclasses import fields

from application.config import ApplicationConfig
from application.evidence.chunked_evidence_extractor import ChunkedEvidenceExtractor
from application.evidence.evidence_extraction_diagnostics import (
    EvidenceExtractionDiagnostics,
    InnerChunkObservation,
    activate_diagnostics,
    deactivate_diagnostics,
    record_inner_chunk_observation,
)
from application.evidence.evidence_extraction_service import EvidenceExtractionService
from application.evidence.evidence_extractor_response_shape import (
    DEFAULT_RESPONSE_PREVIEW_MAX_LENGTH,
    ResponseShapeDiagnostics,
    consume_response_shape,
)
from application.evidence.evidence_response_classification import (
    EvidenceResponseClassification,
    classify_evidence_llm_response,
)
from application.evidence.exceptions import (
    EvidenceExtractionError,
    EvidenceResponseOutcomeError,
)
from application.evidence.evidence_result_codec import extract_evidence_extraction
from application.evidence.provenance_validation import (
    InvalidProvenanceError,
    validate_candidate_provenance,
)
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

REPO_ROOT = Path(__file__).resolve().parents[3]
VALID_ITEM = {
    "statement": "Market size is growing.",
    "source_excerpt": "Exact excerpt in source.",
    "information_need_id": "IN1",
}
LIVE_PARTIAL_Q1 = '{"items":[{"statement":"Serbia remains among European countries",'
LIVE_PARTIAL_Q3 = '{"items":[{"statement":"Among 25–34-year-olds",'
HISTORICAL_INVALID_PREVIEW = (
    '{"items":[{"statement":"Belgrade is the leading urban tourism hotspot"'
)


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


def _extractor(response: LLMResponse) -> tuple[LlmEvidenceExtractor, Mock]:
    client = Mock()
    client.generate.return_value = response
    return LlmEvidenceExtractor(llm_client=client), client


def _classify(response: LLMResponse) -> EvidenceResponseClassification:
    classification, _ = classify_evidence_llm_response(
        response,
        json_extractor=JsonExtractor(),
        json_validator=JsonValidator(),
    )
    return classification


def _extract(response: LLMResponse):
    extractor, client = _extractor(response)
    try:
        candidates = extractor.extract(
            source=_source(),
            design=_design("IN1"),
            run_context=_run_context("IN1"),
        )
        return candidates, consume_response_shape(), None, client
    except Exception as exc:
        return [], consume_response_shape(), exc, client


def _completion_fields(shape: dict) -> dict:
    return {
        key: shape[key]
        for key in (
            "completion_finish_reason",
            "completion_incomplete_reason",
            "completion_was_truncated",
            "completion_output_tokens",
            "completion_reasoning_tokens",
            "completion_max_output_tokens",
            "completion_configured_reasoning_effort",
            "response_text_length",
            "response_preview",
            "response_preview_truncated",
        )
    }


class CanonicalAcceptanceMatrixTests(unittest.TestCase):
    def test_case_a_valid_candidates(self) -> None:
        response = LLMResponse(
            content=json.dumps({"items": [VALID_ITEM]}),
            finish_reason="stop",
            output_tokens=80,
            reasoning_tokens=20,
            max_output_tokens=4096,
        )
        candidates, shape, exc, client = _extract(response)
        self.assertIsNone(exc)
        self.assertGreater(len(candidates), 0)
        assert shape is not None
        self.assertEqual(shape.response_classification, "valid_candidates")
        self.assertTrue(shape.parser_succeeded)
        self.assertEqual(client.generate.call_count, 1)
        options = client.generate.call_args.kwargs["options"]
        self.assertEqual(options.reasoning_effort, "minimal")
        self.assertIsNone(options.max_output_tokens)

    def test_case_b_valid_empty_result(self) -> None:
        candidates, shape, exc, _ = _extract(
            LLMResponse(content='{"items":[]}', finish_reason="stop"),
        )
        self.assertIsNone(exc)
        self.assertEqual(candidates, [])
        assert shape is not None
        self.assertEqual(shape.response_classification, "valid_empty_result")
        self.assertTrue(shape.parser_succeeded)

    def test_case_c_empty_provider_output(self) -> None:
        candidates, shape, exc, _ = _extract(
            LLMResponse(content="", finish_reason="stop"),
        )
        self.assertEqual(candidates, [])
        self.assertIsInstance(exc, EvidenceResponseOutcomeError)
        assert isinstance(exc, EvidenceResponseOutcomeError)
        self.assertEqual(exc.classification, "empty_provider_output")
        assert shape is not None
        self.assertEqual(shape.response_classification, "empty_provider_output")
        self.assertEqual(shape.response_text_length, 0)

    def test_case_d_whitespace_only_is_invalid_json(self) -> None:
        candidates, shape, exc, _ = _extract(
            LLMResponse(content="   \n\t", finish_reason="stop"),
        )
        self.assertIsInstance(exc, EvidenceResponseOutcomeError)
        assert isinstance(exc, EvidenceResponseOutcomeError)
        self.assertEqual(exc.classification, "invalid_json")
        assert shape is not None
        self.assertEqual(shape.response_classification, "invalid_json")
        self.assertGreater(shape.response_text_length, 0)

    def test_case_e_incomplete_empty(self) -> None:
        response = LLMResponse(
            content="",
            finish_reason="length",
            incomplete_reason="max_output_tokens",
            output_tokens=4096,
            reasoning_tokens=4096,
            max_output_tokens=4096,
        )
        _, shape, exc, _ = _extract(response)
        assert isinstance(exc, EvidenceResponseOutcomeError)
        self.assertEqual(exc.classification, "incomplete_provider_output")
        assert shape is not None
        self.assertEqual(shape.response_classification, "incomplete_provider_output")
        self.assertTrue(shape.completion_was_truncated)
        self.assertEqual(shape.completion_incomplete_reason, "max_output_tokens")

    def test_case_f_incomplete_partial_json(self) -> None:
        _, shape, exc, _ = _extract(
            LLMResponse(
                content=LIVE_PARTIAL_Q1,
                finish_reason="length",
                incomplete_reason="max_output_tokens",
            ),
        )
        assert isinstance(exc, EvidenceResponseOutcomeError)
        self.assertEqual(exc.classification, "incomplete_provider_output")
        assert shape is not None
        self.assertEqual(shape.response_classification, "incomplete_provider_output")
        self.assertNotEqual(shape.response_classification, "invalid_json")

    def test_case_g_incomplete_valid_empty_items(self) -> None:
        classification = _classify(
            LLMResponse(
                content='{"items":[]}',
                finish_reason="length",
                incomplete_reason="max_output_tokens",
            ),
        )
        self.assertEqual(classification, EvidenceResponseClassification.INCOMPLETE_PROVIDER_OUTPUT)

    def test_case_h_incomplete_valid_candidates(self) -> None:
        classification = _classify(
            LLMResponse(
                content=json.dumps({"items": [VALID_ITEM]}),
                finish_reason="length",
                incomplete_reason="max_output_tokens",
            ),
        )
        self.assertEqual(classification, EvidenceResponseClassification.INCOMPLETE_PROVIDER_OUTPUT)

    def test_case_i_completed_malformed_json(self) -> None:
        _, shape, exc, _ = _extract(
            LLMResponse(content='{"items":[{"statement":"partial"', finish_reason="stop"),
        )
        assert isinstance(exc, EvidenceResponseOutcomeError)
        self.assertEqual(exc.classification, "invalid_json")
        assert shape is not None
        self.assertFalse(shape.completion_was_truncated)

    def test_case_j_root_array(self) -> None:
        _, _, exc, _ = _extract(LLMResponse(content="[]", finish_reason="stop"))
        assert isinstance(exc, EvidenceResponseOutcomeError)
        self.assertEqual(exc.classification, "root_type_mismatch")

    def test_case_k_root_string(self) -> None:
        _, _, exc, _ = _extract(LLMResponse(content=json.dumps("text"), finish_reason="stop"))
        assert isinstance(exc, EvidenceResponseOutcomeError)
        self.assertEqual(exc.classification, "root_type_mismatch")

    def test_case_l_root_null(self) -> None:
        _, _, exc, _ = _extract(LLMResponse(content="null", finish_reason="stop"))
        assert isinstance(exc, EvidenceResponseOutcomeError)
        self.assertEqual(exc.classification, "root_type_mismatch")

    def test_case_m_missing_items(self) -> None:
        _, _, exc, _ = _extract(LLMResponse(content='{"evidence":[]}', finish_reason="stop"))
        assert isinstance(exc, EvidenceResponseOutcomeError)
        self.assertEqual(exc.classification, "schema_contract_mismatch")

    def test_case_n_items_null(self) -> None:
        _, _, exc, _ = _extract(LLMResponse(content='{"items":null}', finish_reason="stop"))
        assert isinstance(exc, EvidenceResponseOutcomeError)
        self.assertEqual(exc.classification, "schema_contract_mismatch")
        self.assertNotEqual(type(exc).__name__, "TypeError")

    def test_case_o_items_wrong_type(self) -> None:
        for content in ('{"items":"foo"}', '{"items":{"x":1}}'):
            with self.subTest(content=content):
                _, _, exc, _ = _extract(LLMResponse(content=content, finish_reason="stop"))
                assert isinstance(exc, EvidenceResponseOutcomeError)
                self.assertEqual(exc.classification, "schema_contract_mismatch")

    def test_case_p_item_filter_keeps_valid_candidates_class(self) -> None:
        payload = {
            "items": [
                {
                    "statement": "",
                    "source_excerpt": "Exact excerpt in source.",
                    "information_need_id": "IN1",
                },
            ],
        }
        candidates, shape, exc, _ = _extract(
            LLMResponse(content=json.dumps(payload), finish_reason="stop"),
        )
        self.assertIsNone(exc)
        self.assertEqual(candidates, [])
        assert shape is not None
        self.assertEqual(shape.response_classification, "valid_candidates")
        self.assertEqual(shape.rejected_empty_statement, 1)

    def test_case_q_grounding_rejection_keeps_valid_candidates(self) -> None:
        payload = {
            "items": [
                {
                    "statement": "Market size is growing.",
                    "source_excerpt": "This excerpt is not in the source.",
                    "information_need_id": "IN1",
                },
            ],
        }
        source_repo = InMemorySourceRepository()
        source_repo.create(_source())
        service = EvidenceExtractionService(
            evidence_extractor=ChunkedEvidenceExtractor(
                _extractor(LLMResponse(content=json.dumps(payload), finish_reason="stop"))[0],
            ),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=source_repo,
        )
        summary = service.extract_for_source_ids(
            _workflow_context(_design("IN1")),
            ("source-1",),
            allow_empty=True,
        )
        assert summary.diagnostics is not None
        shape = summary.diagnostics.work_items[0].inner_chunks[0].response_shape
        assert shape is not None
        self.assertEqual(shape.response_classification, "valid_candidates")
        self.assertEqual(summary.evidence_extracted, 0)

    def test_case_r_provenance_rejection_keeps_valid_candidates(self) -> None:
        candidates, shape, exc, _ = _extract(
            LLMResponse(content=json.dumps({"items": [VALID_ITEM]}), finish_reason="stop"),
        )
        self.assertIsNone(exc)
        self.assertEqual(len(candidates), 1)
        assert shape is not None
        self.assertEqual(shape.response_classification, "valid_candidates")
        with self.assertRaises(InvalidProvenanceError):
            validate_candidate_provenance(
                candidates[0],
                run_context=_run_context("OTHER"),
                design=_design("IN1"),
            )
        self.assertEqual(shape.response_classification, "valid_candidates")


class PrecedenceAcceptanceTests(unittest.TestCase):
    def test_incomplete_overrides_all_lower_layers(self) -> None:
        fixtures = [
            "",
            '{"items":[]}',
            json.dumps({"items": [VALID_ITEM]}),
            '{"items":[{"statement":"partial"',
            "[]",
            '{"evidence":[]}',
        ]
        for content in fixtures:
            with self.subTest(content=content[:40]):
                classification = _classify(
                    LLMResponse(
                        content=content,
                        finish_reason="length",
                        incomplete_reason="max_output_tokens",
                    ),
                )
                self.assertEqual(
                    classification,
                    EvidenceResponseClassification.INCOMPLETE_PROVIDER_OUTPUT,
                )

    def test_empty_overrides_json_layers_when_complete(self) -> None:
        self.assertEqual(
            _classify(LLMResponse(content="", finish_reason="stop")),
            EvidenceResponseClassification.EMPTY_PROVIDER_OUTPUT,
        )


class LiveShapeReproductionTests(unittest.TestCase):
    def test_historical_and_latest_content_shapes(self) -> None:
        historical_proven = [
            (json.dumps({"items": [VALID_ITEM, VALID_ITEM]}), "valid_candidates"),
            ('{"items":[]}', "valid_empty_result"),
            (HISTORICAL_INVALID_PREVIEW + ",", "invalid_json"),
        ]
        latest_proven = [
            ('{"items":[]}', "valid_empty_result"),
            (LIVE_PARTIAL_Q1, "invalid_json"),
            (LIVE_PARTIAL_Q3, "invalid_json"),
            ("", "empty_provider_output"),
        ]
        for content, expected in historical_proven + latest_proven:
            with self.subTest(content=content[:48], expected=expected):
                classification = _classify(LLMResponse(content=content, finish_reason="stop"))
                self.assertEqual(classification.value, expected)

    def test_hypothetical_incomplete_metadata_on_live_partials(self) -> None:
        for content in (LIVE_PARTIAL_Q1, LIVE_PARTIAL_Q3, ""):
            classification = _classify(
                LLMResponse(
                    content=content,
                    finish_reason="length",
                    incomplete_reason="max_output_tokens",
                ),
            )
            self.assertEqual(classification.value, "incomplete_provider_output")


class CompletionMetadataPersistenceTests(unittest.TestCase):
    def test_known_and_unknown_token_metadata(self) -> None:
        known = LLMResponse(
            content='{"items":[]}',
            finish_reason="stop",
            output_tokens=12,
            reasoning_tokens=4,
            max_output_tokens=4096,
            configured_reasoning_effort=None,
        )
        _, shape, _, _ = _extract(known)
        assert shape is not None
        payload = shape.to_dict()
        fields = _completion_fields(payload)
        self.assertEqual(fields["completion_finish_reason"], "stop")
        self.assertIsNone(fields["completion_incomplete_reason"])
        self.assertFalse(fields["completion_was_truncated"])
        self.assertEqual(fields["completion_output_tokens"], 12)
        self.assertEqual(fields["completion_reasoning_tokens"], 4)
        self.assertEqual(fields["completion_max_output_tokens"], 4096)
        self.assertIsNone(fields["completion_configured_reasoning_effort"])
        self.assertEqual(fields["response_text_length"], len('{"items":[]}'))

        unknown = LLMResponse(content='{"items":[]}', finish_reason="stop")
        _, unknown_shape, _, _ = _extract(unknown)
        assert unknown_shape is not None
        unknown_payload = unknown_shape.to_dict()
        self.assertIsNone(unknown_payload["completion_output_tokens"])
        self.assertIsNone(unknown_payload["completion_reasoning_tokens"])
        self.assertIsNone(unknown_payload["completion_max_output_tokens"])

    def test_success_and_failure_survive_persister(self) -> None:
        for content, expected_class, expect_error in (
            (json.dumps({"items": [VALID_ITEM]}), "valid_candidates", False),
            ("", "empty_provider_output", True),
        ):
            with self.subTest(expected_class=expected_class):
                source_repo = InMemorySourceRepository()
                source_repo.create(_source())
                response = LLMResponse(content=content, finish_reason="stop", output_tokens=9)
                executor = EvidenceExecutor(
                    evidence_extraction_service=EvidenceExtractionService(
                        evidence_extractor=ChunkedEvidenceExtractor(
                            _extractor(response)[0],
                        ),
                        evidence_repository=InMemoryEvidenceRepository(),
                        source_repository=source_repo,
                    ),
                )
                context = _workflow_context(_design("IN1"))
                if expect_error:
                    with self.assertRaises(EvidenceExtractionError):
                        executor.run(context)
                else:
                    executor.run(context)
                inner = context.shared_state["evidence_extraction"]["diagnostics"]["work_items"][0][
                    "inner_chunks"
                ][0]
                self.assertEqual(inner["response_shape"]["response_classification"], expected_class)
                self.assertEqual(inner["response_shape"]["completion_output_tokens"], 9)
                task = context.current_task
                assert task is not None
                task.ready()
                task.start()
                if expect_error:
                    task.fail()
                    error: Exception | None = EvidenceExtractionError("failed")
                else:
                    task.complete()
                    error = None
                persister = WorkflowRuntimePersister(
                    workflow_service=mock.Mock(),
                    audit=mock.Mock(),
                    run_id=context.workflow_run.id,
                )
                persister.on_task_finished(context, error=error)
                payload = extract_evidence_extraction(persister.task_results)
                assert payload is not None
                persisted = payload["diagnostics"]["work_items"][0]["inner_chunks"][0][
                    "response_shape"
                ]
                self.assertEqual(persisted["response_classification"], expected_class)
                self.assertEqual(persisted["completion_finish_reason"], "stop")


class AggregateDiagnosticsAcceptanceTests(unittest.TestCase):
    def test_mixed_response_classification_counts(self) -> None:
        diagnostics = EvidenceExtractionDiagnostics(workflow_run_id="run-obs")
        token = activate_diagnostics(diagnostics)
        try:
            classes = [
                "incomplete_provider_output",
                "empty_provider_output",
                "invalid_json",
                "root_type_mismatch",
                "schema_contract_mismatch",
                "valid_empty_result",
                "valid_candidates",
            ]
            for index, classification in enumerate(classes):
                shape = ResponseShapeDiagnostics(provider_response_received=True)
                shape.response_classification = classification
                record_inner_chunk_observation(
                    InnerChunkObservation(
                        inner_chunk_index=index,
                        inner_chunk_normalized_start=0,
                        inner_chunk_normalized_end=1,
                        inner_chunk_length=1,
                        extractor_status=(
                            "success"
                            if classification in {"valid_empty_result", "valid_candidates"}
                            else "exception"
                        ),
                        response_shape=shape,
                    ),
                )
        finally:
            deactivate_diagnostics(token)
        counts = diagnostics.to_dict()["response_classification_counts"]
        self.assertEqual(
            counts,
            {
                "incomplete_provider_output": 1,
                "empty_provider_output": 1,
                "invalid_json": 1,
                "root_type_mismatch": 1,
                "schema_contract_mismatch": 1,
                "valid_empty_result": 1,
                "valid_candidates": 1,
            },
        )

    def test_stage_failure_classification_not_replaced(self) -> None:
        source_repo = InMemorySourceRepository()
        source_repo.create(_source())
        service = EvidenceExtractionService(
            evidence_extractor=ChunkedEvidenceExtractor(
                _extractor(LLMResponse(content='{"items":[]}', finish_reason="stop"))[0],
            ),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=source_repo,
        )
        summary = service.extract_for_source_ids(
            _workflow_context(_design("IN1")),
            ("source-1",),
            allow_empty=True,
        )
        assert summary.diagnostics is not None
        payload = summary.diagnostics.to_dict()
        self.assertEqual(
            payload["work_items"][0]["inner_chunks"][0]["response_shape"][
                "response_classification"
            ],
            "valid_empty_result",
        )
        self.assertIn(payload["failure_classification"], {"success", "no_candidates"})
        self.assertNotEqual(payload["failure_classification"], "valid_empty_result")


class BudgetCostInvariantTests(unittest.TestCase):
    def test_classifier_does_not_call_llm(self) -> None:
        client = Mock()
        classify_evidence_llm_response(
            LLMResponse(content='{"items":[]}', finish_reason="stop"),
            json_extractor=JsonExtractor(),
            json_validator=JsonValidator(),
        )
        client.generate.assert_not_called()

    def test_one_generate_call_per_extract(self) -> None:
        _, _, _, client = _extract(LLMResponse(content='{"items":[]}', finish_reason="stop"))
        self.assertEqual(client.generate.call_count, 1)

    def test_live_desk_evidence_cap_and_token_defaults_unchanged(self) -> None:
        compose = (REPO_ROOT / "docker-compose.lowcost.yml").read_text(encoding="utf-8")
        self.assertIn('EVIDENCE_MAX_LLM_CALLS: "8"', compose)
        defaults = {item.name: item.default for item in fields(ApplicationConfig)}
        self.assertEqual(defaults["llm_max_tokens"], 4096)
        self.assertEqual(defaults["evidence_reasoning_effort"], "minimal")


class ProviderNeutralityAndPrivacyTests(unittest.TestCase):
    def test_evidence_modules_do_not_import_openai(self) -> None:
        forbidden = ("openai", "incomplete_details", "ResponseOutputItem", "EasyInputMessage")
        roots = [
            REPO_ROOT / "application" / "evidence",
            REPO_ROOT / "infrastructure" / "evidence" / "llm_evidence_extractor.py",
        ]
        files: list[Path] = []
        for root in roots:
            if root.is_file():
                files.append(root)
            else:
                files.extend(root.rglob("*.py"))
        for path in files:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn("openai", alias.name.lower())
                if isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn("openai", node.module.lower())
            lowered = source.lower()
            for token in forbidden[1:]:
                self.assertNotIn(token.lower(), lowered, msg=f"{token} leaked in {path}")

    def test_preview_remains_bounded(self) -> None:
        content = '{"items":[' + ('{"statement":"x"},' * 200)
        _, shape, _, _ = _extract(LLMResponse(content=content, finish_reason="stop"))
        assert shape is not None
        payload = shape.to_dict()
        self.assertTrue(payload["response_preview_truncated"])
        self.assertLessEqual(
            len(payload["response_preview"]),
            DEFAULT_RESPONSE_PREVIEW_MAX_LENGTH + 1,
        )
        self.assertGreater(payload["response_text_length"], DEFAULT_RESPONSE_PREVIEW_MAX_LENGTH)


if __name__ == "__main__":
    unittest.main()

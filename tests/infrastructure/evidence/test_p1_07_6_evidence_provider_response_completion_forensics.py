"""P1-07.6 offline forensic tests for Evidence provider response completion."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source

from application.evidence.exceptions import EvidenceResponseOutcomeError
from application.evidence.evidence_extractor_response_shape import (
    ResponseShapeDiagnostics,
)
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.structured_output.json_extractor import JsonExtractor
from application.structured_output.json_validator import JsonValidator
from infrastructure.evidence.llm_evidence_extractor import LlmEvidenceExtractor
from infrastructure.llm.llm_configuration import LLMConfiguration
from infrastructure.llm.openai_client import OpenAIClient


def _design(*need_ids: str) -> ResearchDesign:
    if not need_ids:
        need_ids = ("IN1",)
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
    if not need_ids:
        need_ids = ("IN1",)
    return RunScopedSourceContext(
        workflow_run_id="run-1",
        research_design_id="design-1",
        information_need_ids=need_ids,
        research_question_ids=("RQ1",),
        query_ids=tuple(f"sq-{need_id}" for need_id in need_ids),
    )


def _sdk_response(**kwargs):
    defaults = {
        "status": "completed",
        "output_text": "",
        "usage": SimpleNamespace(
            output_tokens=0,
            output_tokens_details=SimpleNamespace(reasoning_tokens=0),
        ),
        "incomplete_details": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class OpenAIClientNormalizationForensicsTests(unittest.TestCase):
    @patch("openai.OpenAI")
    def test_completed_json_maps_to_llm_response(self, openai_cls):
        api = Mock()
        openai_cls.return_value = api
        api.responses.create.return_value = _sdk_response(
            status="completed",
            output_text='{"items":[]}',
            usage=SimpleNamespace(
                output_tokens=42,
                output_tokens_details=SimpleNamespace(reasoning_tokens=10),
            ),
        )
        client = OpenAIClient(LLMConfiguration(model="gpt-5", max_tokens=4096))
        response = client.generate(Prompt(system="S", user="U"))

        self.assertEqual(response.content, '{"items":[]}')
        self.assertEqual(response.finish_reason, "stop")
        self.assertEqual(response.output_tokens, 42)
        self.assertEqual(response.reasoning_tokens, 10)
        self.assertIsNone(response.incomplete_reason)

    @patch("openai.OpenAI")
    def test_incomplete_max_output_tokens_maps_to_length_finish_reason(self, openai_cls):
        api = Mock()
        openai_cls.return_value = api
        truncated = '{"items":[{"statement":"Serbia remains among European countries",'
        api.responses.create.return_value = _sdk_response(
            status="incomplete",
            output_text=truncated,
            incomplete_details=SimpleNamespace(reason="max_output_tokens"),
            usage=SimpleNamespace(
                output_tokens=4096,
                output_tokens_details=SimpleNamespace(reasoning_tokens=3500),
            ),
        )
        client = OpenAIClient(LLMConfiguration(model="gpt-5", max_tokens=4096))
        response = client.generate(Prompt(system="S", user="U"))

        self.assertEqual(response.content, truncated)
        self.assertEqual(response.finish_reason, "length")
        self.assertEqual(response.incomplete_reason, "max_output_tokens")
        self.assertTrue(response.was_truncated)

    @patch("openai.OpenAI")
    def test_empty_output_text_maps_to_zero_length_content(self, openai_cls):
        api = Mock()
        openai_cls.return_value = api
        api.responses.create.return_value = _sdk_response(
            status="incomplete",
            output_text="",
            incomplete_details=SimpleNamespace(reason="max_output_tokens"),
            usage=SimpleNamespace(
                output_tokens=4096,
                output_tokens_details=SimpleNamespace(reasoning_tokens=4096),
            ),
        )
        client = OpenAIClient(LLMConfiguration(model="gpt-5", max_tokens=4096))
        response = client.generate(Prompt(system="S", user="U"))

        self.assertEqual(response.content, "")
        self.assertEqual(len(response.content), 0)
        self.assertEqual(response.finish_reason, "length")
        self.assertEqual(response.incomplete_reason, "max_output_tokens")


class ResponseShapeForensicsTests(unittest.TestCase):
    def _shape(self, content: str) -> ResponseShapeDiagnostics:
        return ResponseShapeDiagnostics.from_response_content(
            content,
            json_extractor=JsonExtractor(),
            json_validator=JsonValidator(),
        )

    def test_b_completed_empty_items(self) -> None:
        shape = self._shape('{"items":[]}')
        self.assertEqual(shape.parsed_root_type, "object")
        self.assertIsNone(shape.items_count_pre_filter)

    def test_c_non_empty_incomplete_json_live_q1_shape(self) -> None:
        content = '{"items":[{"statement":"Serbia remains among European countries",'
        shape = self._shape(content)
        self.assertEqual(shape.response_text_length, len(content))
        self.assertEqual(shape.json_container_count, 1)
        self.assertEqual(shape.parsed_root_type, "no_valid_json")
        self.assertFalse(shape.parser_succeeded)

    def test_d_zero_length_output_live_q2_shape(self) -> None:
        shape = self._shape("")
        self.assertEqual(shape.response_text_length, 0)
        self.assertEqual(shape.json_container_count, 0)
        self.assertEqual(shape.parsed_root_type, "no_valid_json")

    def test_completion_metadata_fields_use_provider_neutral_names(self) -> None:
        fields = ResponseShapeDiagnostics.__dataclass_fields__
        self.assertIn("completion_finish_reason", fields)
        self.assertIn("completion_incomplete_reason", fields)
        self.assertIn("completion_was_truncated", fields)
        self.assertIn("completion_output_tokens", fields)
        self.assertNotIn("finish_reason", fields)
        self.assertNotIn("incomplete_reason", fields)
        self.assertNotIn("visible_output_length", fields)


class LlmEvidenceExtractorProviderPathForensicsTests(unittest.TestCase):
    def _extract(self, response: LLMResponse) -> tuple[ResponseShapeDiagnostics | None, Exception | None]:
        mock_client = Mock()
        mock_client.generate.return_value = response
        extractor = LlmEvidenceExtractor(llm_client=mock_client)
        from application.evidence.evidence_extractor_response_shape import consume_response_shape

        exc: Exception | None = None
        try:
            extractor.extract(
                source=_source(),
                design=_design(),
                run_context=_run_context(),
            )
        except Exception as caught:
            exc = caught
        return consume_response_shape(), exc

    def test_q2_q5_zero_length_incomplete_produces_typed_outcome(self) -> None:
        shape, exc = self._extract(
            LLMResponse(
                content="",
                finish_reason="length",
                incomplete_reason="max_output_tokens",
                output_tokens=4096,
                max_output_tokens=4096,
                reasoning_tokens=4096,
            ),
        )
        assert shape is not None
        self.assertEqual(shape.response_text_length, 0)
        self.assertEqual(shape.json_container_count, 0)
        self.assertIsInstance(exc, EvidenceResponseOutcomeError)
        self.assertEqual(
            exc.classification,
            "incomplete_provider_output",
        )

    def test_q1_q3_incomplete_json_produces_typed_outcome(self) -> None:
        content = '{"items":[{"statement":"Among 25–34-year-olds",'
        shape, exc = self._extract(
            LLMResponse(
                content=content,
                finish_reason="length",
                incomplete_reason="max_output_tokens",
                output_tokens=4096,
                max_output_tokens=4096,
            ),
        )
        assert shape is not None
        self.assertGreater(shape.response_text_length, 0)
        self.assertIsInstance(exc, EvidenceResponseOutcomeError)
        self.assertEqual(
            exc.classification,
            "incomplete_provider_output",
        )

    def test_incomplete_valid_empty_items_is_not_valid_empty_result(self) -> None:
        content = '{"items":[]}'
        shape, exc = self._extract(
            LLMResponse(
                content=content,
                finish_reason="length",
                incomplete_reason="max_output_tokens",
            ),
        )
        assert shape is not None
        self.assertIsInstance(exc, EvidenceResponseOutcomeError)
        self.assertEqual(shape.completion_finish_reason, "length")
        self.assertEqual(shape.completion_incomplete_reason, "max_output_tokens")
        self.assertTrue(shape.completion_was_truncated)
        self.assertEqual(
            shape.response_classification,
            "incomplete_provider_output",
        )

    def test_evidence_generate_called_without_options(self) -> None:
        mock_client = Mock()
        mock_client.generate.return_value = LLMResponse(content='{"items":[]}')
        extractor = LlmEvidenceExtractor(llm_client=mock_client)
        extractor.extract(
            source=_source(),
            design=_design(),
            run_context=_run_context(),
        )
        mock_client.generate.assert_called_once()
        self.assertNotIn("options", mock_client.generate.call_args.kwargs)


def _extractor_with_response(response: LLMResponse) -> LlmEvidenceExtractor:
    mock_client = Mock()
    mock_client.generate.return_value = response
    return LlmEvidenceExtractor(llm_client=mock_client)


class ErrorMessageCollapseForensicsTests(unittest.TestCase):
    def test_parse_payload_still_collapses_invalid_root_shapes(self) -> None:
        extractor = LlmEvidenceExtractor(llm_client=Mock())
        cases = [
            '{"items":[{"statement":"partial"',
            "[]",
        ]
        messages: set[str] = set()
        for content in cases:
            with self.assertRaises(ValueError) as ctx:
                extractor._parse_payload(content)
            messages.add(str(ctx.exception))
        self.assertEqual(len(messages), 1)
        self.assertIn("must be a JSON object", messages.pop())

    def test_empty_output_uses_distinct_typed_outcome(self) -> None:
        extractor = _extractor_with_response(LLMResponse(content="", finish_reason="stop"))
        with self.assertRaises(EvidenceResponseOutcomeError) as ctx:
            extractor.extract(
                source=_source(),
                design=_design(),
                run_context=_run_context(),
            )
        self.assertNotIn("must be a JSON object", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

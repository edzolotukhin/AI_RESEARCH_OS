"""P1-07.7.1 Evidence reasoning-policy hardening tests."""

from __future__ import annotations

import json
import os
import unittest
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source

from application.config import ApplicationConfig, ApplicationOverrides
from application.evidence.evidence_extractor_response_shape import consume_response_shape
from application.evidence.evidence_factory import build_evidence_extractor
from application.evidence.evidence_response_classification import EvidenceResponseClassification
from application.evidence.exceptions import EvidenceResponseOutcomeError
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.structured_output.generation_policy import REASONING_EFFORT_ORDER
from infrastructure.evidence.llm_evidence_extractor import LlmEvidenceExtractor
from infrastructure.llm.generation_options import LLMGenerationOptions
from infrastructure.llm.llm_configuration import LLMConfiguration
from infrastructure.llm.openai_client import OpenAIClient

REPO_ROOT = Path(__file__).resolve().parents[3]
VALID_ITEM = {
    "statement": "Market size is growing.",
    "source_excerpt": "Exact excerpt in source.",
    "information_need_id": "IN1",
}


def _design() -> ResearchDesign:
    return ResearchDesign(
        id="design-1",
        language="en",
        research_questions=(
            ResearchQuestion(id="RQ1", question="Question?", objective_refs=()),
        ),
        information_needs=(
            InformationNeed(
                id="IN1",
                research_question_id="RQ1",
                description="Need IN1",
            ),
        ),
    )


def _source() -> Source:
    return Source(
        id="source-1",
        project_id="project-1",
        url="https://example.com",
        canonical_url="https://example.com",
        title="Title",
        retrieved_at="2026-01-01T00:00:00+00:00",
        retrieval_status=RetrievalStatus.ACQUIRED,
        content_text="Exact excerpt in source.",
    )


def _run_context() -> RunScopedSourceContext:
    return RunScopedSourceContext(
        workflow_run_id="run-1",
        research_design_id="design-1",
        information_need_ids=("IN1",),
        research_question_ids=("RQ1",),
        query_ids=("sq-IN1",),
    )


def _echoing_client(content: str = '{"items":[]}') -> Mock:
    client = Mock()

    def _generate(prompt, *, options=None):
        return LLMResponse(
            content=content,
            finish_reason="stop",
            configured_reasoning_effort=(
                options.reasoning_effort if options is not None else None
            ),
        )

    client.generate.side_effect = _generate
    return client


class EvidenceReasoningConfigTests(unittest.TestCase):
    def test_a_default_config_is_minimal(self) -> None:
        self.assertEqual(ApplicationConfig().evidence_reasoning_effort, "minimal")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EVIDENCE_REASONING_EFFORT", None)
            config = ApplicationConfig.from_env()
        self.assertEqual(config.evidence_reasoning_effort, "minimal")

    def test_b_valid_override_low(self) -> None:
        with patch.dict(os.environ, {"EVIDENCE_REASONING_EFFORT": " LOW "}, clear=False):
            config = ApplicationConfig.from_env()
        self.assertEqual(config.evidence_reasoning_effort, "low")

    def test_c_invalid_override_matches_other_stages(self) -> None:
        with patch.dict(
            os.environ,
            {
                "EVIDENCE_REASONING_EFFORT": " BANANA ",
                "SUFFICIENCY_REASONING_EFFORT": " BANANA ",
            },
            clear=False,
        ):
            config = ApplicationConfig.from_env()
        self.assertEqual(config.evidence_reasoning_effort, "banana")
        self.assertEqual(config.sufficiency_reasoning_effort, "banana")
        self.assertNotIn("banana", REASONING_EFFORT_ORDER)

    def test_other_stage_reasoning_defaults_unchanged(self) -> None:
        config = ApplicationConfig()
        self.assertEqual(config.planner_reasoning_effort, "minimal")
        self.assertEqual(config.sufficiency_reasoning_effort, "minimal")
        self.assertEqual(config.analysis_reasoning_effort, "minimal")
        self.assertEqual(config.report_reasoning_effort, "minimal")
        self.assertEqual(config.review_reasoning_effort, "minimal")


class EvidenceReasoningFactoryAndCallTests(unittest.TestCase):
    def test_d_factory_injects_configured_value(self) -> None:
        client = Mock()
        extractor = build_evidence_extractor(
            ApplicationConfig(evidence_reasoning_effort="low"),
            ApplicationOverrides(),
            llm_client=client,
        )
        inner = extractor._inner
        self.assertIsInstance(inner, LlmEvidenceExtractor)
        self.assertEqual(inner._reasoning_effort, "low")

    def test_e_default_extractor_sends_minimal_once(self) -> None:
        client = _echoing_client()
        extractor = LlmEvidenceExtractor(llm_client=client)
        extractor.extract(source=_source(), design=_design(), run_context=_run_context())
        self.assertEqual(client.generate.call_count, 1)
        options = client.generate.call_args.kwargs["options"]
        self.assertIsInstance(options, LLMGenerationOptions)
        self.assertEqual(options.reasoning_effort, "minimal")
        self.assertIsNone(options.max_output_tokens)

    def test_f_override_extractor_sends_configured_effort_once(self) -> None:
        client = _echoing_client()
        extractor = LlmEvidenceExtractor(llm_client=client, reasoning_effort="low")
        extractor.extract(source=_source(), design=_design(), run_context=_run_context())
        self.assertEqual(client.generate.call_count, 1)
        options = client.generate.call_args.kwargs["options"]
        self.assertEqual(options.reasoning_effort, "low")
        self.assertIsNone(options.max_output_tokens)

    def test_g_no_token_cap_change_on_options(self) -> None:
        client = _echoing_client()
        LlmEvidenceExtractor(llm_client=client).extract(
            source=_source(),
            design=_design(),
            run_context=_run_context(),
        )
        options = client.generate.call_args.kwargs["options"]
        self.assertIsNone(options.max_output_tokens)
        defaults = {item.name: item.default for item in fields(ApplicationConfig)}
        self.assertEqual(defaults["llm_max_tokens"], 4096)
        self.assertEqual(defaults["evidence_max_llm_calls"], 50)

    def test_h_no_retry_single_generate(self) -> None:
        client = _echoing_client(json.dumps({"items": [VALID_ITEM]}))
        extractor = LlmEvidenceExtractor(llm_client=client)
        candidates = extractor.extract(
            source=_source(),
            design=_design(),
            run_context=_run_context(),
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(client.generate.call_count, 1)


class OpenAIAdapterMappingTests(unittest.TestCase):
    @patch("openai.OpenAI")
    def test_i_minimal_maps_to_reasoning_effort(self, openai_cls) -> None:
        api = Mock()
        openai_cls.return_value = api
        api.responses.create.return_value = SimpleNamespace(
            status="completed",
            output_text='{"items":[]}',
            usage=SimpleNamespace(
                output_tokens=12,
                output_tokens_details=SimpleNamespace(reasoning_tokens=4),
            ),
            incomplete_details=None,
        )
        client = OpenAIClient(LLMConfiguration(model="gpt-5", max_tokens=4096))
        response = client.generate(
            Prompt(system="S", user="U"),
            options=LLMGenerationOptions(reasoning_effort="minimal"),
        )
        kwargs = api.responses.create.call_args.kwargs
        self.assertEqual(kwargs["reasoning"], {"effort": "minimal"})
        self.assertEqual(kwargs["max_output_tokens"], 4096)
        self.assertEqual(response.configured_reasoning_effort, "minimal")


class ObservabilityAndClassificationRegressionTests(unittest.TestCase):
    def test_j_configured_reasoning_effort_persists(self) -> None:
        client = _echoing_client('{"items":[]}')
        extractor = LlmEvidenceExtractor(llm_client=client)
        extractor.extract(source=_source(), design=_design(), run_context=_run_context())
        shape = consume_response_shape()
        assert shape is not None
        self.assertEqual(shape.completion_configured_reasoning_effort, "minimal")
        self.assertEqual(shape.response_classification, "valid_empty_result")

    def test_k_incomplete_classification_unchanged(self) -> None:
        client = Mock()
        client.generate.return_value = LLMResponse(
            content="",
            finish_reason="length",
            incomplete_reason="max_output_tokens",
            configured_reasoning_effort="minimal",
        )
        extractor = LlmEvidenceExtractor(llm_client=client)
        with self.assertRaises(EvidenceResponseOutcomeError) as ctx:
            extractor.extract(source=_source(), design=_design(), run_context=_run_context())
        self.assertEqual(
            ctx.exception.classification,
            EvidenceResponseClassification.INCOMPLETE_PROVIDER_OUTPUT.value,
        )
        self.assertEqual(client.generate.call_count, 1)

    def test_l_valid_empty_result_unchanged(self) -> None:
        client = _echoing_client('{"items":[]}')
        extractor = LlmEvidenceExtractor(llm_client=client)
        candidates = extractor.extract(
            source=_source(),
            design=_design(),
            run_context=_run_context(),
        )
        self.assertEqual(candidates, [])
        shape = consume_response_shape()
        assert shape is not None
        self.assertEqual(shape.response_classification, "valid_empty_result")

    def test_m_valid_candidates_unchanged(self) -> None:
        client = _echoing_client(json.dumps({"items": [VALID_ITEM]}))
        extractor = LlmEvidenceExtractor(llm_client=client)
        candidates = extractor.extract(
            source=_source(),
            design=_design(),
            run_context=_run_context(),
        )
        self.assertEqual(len(candidates), 1)
        shape = consume_response_shape()
        assert shape is not None
        self.assertEqual(shape.response_classification, "valid_candidates")

    def test_n_schema_fail_closed_unchanged(self) -> None:
        client = _echoing_client('{"evidence":[]}')
        extractor = LlmEvidenceExtractor(llm_client=client)
        with self.assertRaises(EvidenceResponseOutcomeError) as ctx:
            extractor.extract(source=_source(), design=_design(), run_context=_run_context())
        self.assertEqual(
            ctx.exception.classification,
            EvidenceResponseClassification.SCHEMA_CONTRACT_MISMATCH.value,
        )


class BudgetComposeInvariantTests(unittest.TestCase):
    def test_lowcost_compose_caps_unchanged(self) -> None:
        compose = (REPO_ROOT / "docker-compose.lowcost.yml").read_text(encoding="utf-8")
        self.assertIn('EVIDENCE_MAX_LLM_CALLS: "8"', compose)
        self.assertIn('LLM_MAX_CALLS_PER_RUN: "24"', compose)
        self.assertNotIn("EVIDENCE_REASONING_EFFORT", compose)


if __name__ == "__main__":
    unittest.main()

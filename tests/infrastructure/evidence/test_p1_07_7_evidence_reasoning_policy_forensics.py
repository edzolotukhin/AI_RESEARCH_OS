"""P1-07.7 forensic tests for Evidence reasoning-policy contracts."""

from __future__ import annotations

import inspect
import unittest
from dataclasses import fields
from types import SimpleNamespace
from unittest.mock import Mock, patch

from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source

from application.config import ApplicationConfig, ApplicationOverrides
from application.evidence.evidence_factory import build_evidence_extractor
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.structured_output.generation_policy import REASONING_EFFORT_ORDER
from infrastructure.evidence.llm_evidence_extractor import LlmEvidenceExtractor
from infrastructure.llm.generation_options import LLMGenerationOptions
from infrastructure.llm.llm_configuration import LLMConfiguration
from infrastructure.llm.openai_client import OpenAIClient


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


class ReasoningEffortContractForensicsTests(unittest.TestCase):
    def test_platform_reasoning_effort_order(self) -> None:
        self.assertEqual(REASONING_EFFORT_ORDER, ("minimal", "low", "medium", "high"))

    def test_generation_options_are_optional_strings(self) -> None:
        options = LLMGenerationOptions()
        self.assertIsNone(options.reasoning_effort)
        self.assertIsNone(options.max_output_tokens)
        typed = LLMGenerationOptions(reasoning_effort="minimal", max_output_tokens=4096)
        self.assertEqual(typed.reasoning_effort, "minimal")

    def test_application_config_has_no_evidence_reasoning_effort(self) -> None:
        names = {item.name for item in fields(ApplicationConfig)}
        self.assertNotIn("evidence_reasoning_effort", names)
        self.assertIn("planner_reasoning_effort", names)
        self.assertIn("sufficiency_reasoning_effort", names)
        self.assertIn("analysis_reasoning_effort", names)
        self.assertIn("report_reasoning_effort", names)
        self.assertIn("review_reasoning_effort", names)

    def test_stage_reasoning_defaults_are_minimal_except_evidence(self) -> None:
        config = ApplicationConfig()
        self.assertEqual(config.planner_reasoning_effort, "minimal")
        self.assertEqual(config.sufficiency_reasoning_effort, "minimal")
        self.assertEqual(config.analysis_reasoning_effort, "minimal")
        self.assertEqual(config.report_reasoning_effort, "minimal")
        self.assertEqual(config.review_reasoning_effort, "minimal")
        self.assertEqual(config.llm_max_tokens, 4096)


class EvidenceCallPathForensicsTests(unittest.TestCase):
    def test_extractor_generate_called_without_options(self) -> None:
        client = Mock()
        client.generate.return_value = LLMResponse(content='{"items":[]}', finish_reason="stop")
        extractor = LlmEvidenceExtractor(llm_client=client)
        extractor.extract(source=_source(), design=_design(), run_context=_run_context())
        client.generate.assert_called_once()
        self.assertNotIn("options", client.generate.call_args.kwargs)
        signature = inspect.signature(extractor.extract)
        self.assertNotIn("reasoning_effort", signature.parameters)

    def test_extractor_constructor_accepts_only_llm_client(self) -> None:
        params = inspect.signature(LlmEvidenceExtractor.__init__).parameters
        self.assertIn("llm_client", params)
        self.assertNotIn("reasoning_effort", params)
        self.assertNotIn("max_output_tokens", params)

    def test_factory_constructs_extractor_without_reasoning_kwargs(self) -> None:
        client = Mock()
        extractor = build_evidence_extractor(
            ApplicationConfig(),
            ApplicationOverrides(),
            llm_client=client,
        )
        inner = extractor._inner
        self.assertIsInstance(inner, LlmEvidenceExtractor)
        self.assertIs(inner._llm_client, client)


class OpenAIAdapterReasoningMappingForensicsTests(unittest.TestCase):
    def _sdk_response(self, *, output_text: str = '{"items":[]}') -> SimpleNamespace:
        return SimpleNamespace(
            status="completed",
            output_text=output_text,
            usage=SimpleNamespace(
                output_tokens=12,
                output_tokens_details=SimpleNamespace(reasoning_tokens=4),
            ),
            incomplete_details=None,
        )

    @patch("openai.OpenAI")
    def test_omitted_options_do_not_send_reasoning_key(self, openai_cls) -> None:
        api = Mock()
        openai_cls.return_value = api
        api.responses.create.return_value = self._sdk_response()
        client = OpenAIClient(LLMConfiguration(model="gpt-5", max_tokens=4096))
        response = client.generate(Prompt(system="S", user="U"))
        kwargs = api.responses.create.call_args.kwargs
        self.assertNotIn("reasoning", kwargs)
        self.assertEqual(kwargs["max_output_tokens"], 4096)
        self.assertIsNone(response.configured_reasoning_effort)
        self.assertEqual(response.finish_reason, "stop")
        self.assertEqual(response.output_tokens, 12)
        self.assertEqual(response.reasoning_tokens, 4)
        self.assertEqual(response.max_output_tokens, 4096)

    @patch("openai.OpenAI")
    def test_explicit_minimal_sends_reasoning_effort(self, openai_cls) -> None:
        api = Mock()
        openai_cls.return_value = api
        api.responses.create.return_value = self._sdk_response()
        client = OpenAIClient(LLMConfiguration(model="gpt-5", max_tokens=4096))
        response = client.generate(
            Prompt(system="S", user="U"),
            options=LLMGenerationOptions(reasoning_effort="minimal"),
        )
        kwargs = api.responses.create.call_args.kwargs
        self.assertEqual(kwargs["reasoning"], {"effort": "minimal"})
        self.assertEqual(response.configured_reasoning_effort, "minimal")
        self.assertEqual(kwargs["max_output_tokens"], 4096)


if __name__ == "__main__":
    unittest.main()

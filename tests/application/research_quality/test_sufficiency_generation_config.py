"""Semantic sufficiency generation configuration and production wiring tests."""

from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from application.config import ApplicationConfig, ApplicationOverrides
from application.execution.execution_budget_retry import consume_llm_call_retry_flag
from application.research_quality.research_quality_factory import (
    build_research_sufficiency_evaluator,
)
from application.research_quality.semantic_sufficiency_contract import (
    semantic_sufficiency_payload_contract,
)
from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt
from domain.evidence.evidence import Evidence
from domain.planning.research_design import InformationNeed, ResearchQuestion
from domain.research_quality.deterministic_sufficiency_signals import (
    DeterministicSufficiencySignals,
)
from domain.research_quality.sufficiency_status import SufficiencyStatus
from infrastructure.llm.generation_options import LLMGenerationOptions
from infrastructure.llm.llm_configuration import LLMConfiguration
from infrastructure.llm.openai_client import OpenAIClient
from infrastructure.research_quality.llm_semantic_sufficiency_assessor import (
    LlmSemanticSufficiencyAssessor,
)
from infrastructure.research_quality.sufficiency_structured_output import (
    DEFAULT_SUFFICIENCY_MAX_OUTPUT_TOKENS,
    SufficiencyStructuredOutputGenerator,
)

from application.research_quality.hybrid_sufficiency_evaluator import (
    HybridResearchSufficiencyEvaluator,
)


def _valid_sufficient_payload() -> dict[str, object]:
    return {
        "status": "sufficient",
        "missing_aspects": [],
        "gap_types": [],
        "search_directives": [],
        "confidence": 0.9,
        "reason": "Evidence substantively answers the information need.",
    }


def _assess_inputs() -> tuple[
    ResearchQuestion,
    InformationNeed,
    tuple[Evidence, ...],
    DeterministicSufficiencySignals,
]:
    return (
        ResearchQuestion(
            id="rq-1",
            question="What is the market outlook?",
            objective_refs=(),
        ),
        InformationNeed(
            id="in-1",
            research_question_id="rq-1",
            description="Need market data",
        ),
        (
            Evidence(
                id="evidence-1",
                project_id="project-1",
                source_id="source-1",
                source_content_checksum="checksum-1",
                workflow_run_id="run-1",
                research_design_id="design-1",
                research_question_refs=("rq-1",),
                information_need_refs=("in-1",),
                statement="Market grew 10%.",
                source_excerpt="Market grew 10% in 2025.",
                created_at="2026-01-01T00:00:00+00:00",
                deduplication_key="dedup-1",
            ),
        ),
        DeterministicSufficiencySignals(
            information_need_id="in-1",
            research_question_id="rq-1",
            evidence_count=1,
            independent_source_count=1,
            evidence_ids=("evidence-1",),
            source_ids=("source-1",),
            deterministic_gap_types=(),
        ),
    )


class ApplicationConfigSufficiencyGenerationTests(unittest.TestCase):
    def test_defaults(self) -> None:
        config = ApplicationConfig()
        self.assertEqual(config.sufficiency_reasoning_effort, "minimal")
        self.assertEqual(config.sufficiency_max_output_tokens, 8192)

    def test_from_env_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SUFFICIENCY_REASONING_EFFORT", None)
            os.environ.pop("SUFFICIENCY_MAX_OUTPUT_TOKENS", None)
            config = ApplicationConfig.from_env()
        self.assertEqual(config.sufficiency_reasoning_effort, "minimal")
        self.assertEqual(config.sufficiency_max_output_tokens, 8192)

    def test_reasoning_effort_env_override(self) -> None:
        with patch.dict(
            os.environ,
            {"SUFFICIENCY_REASONING_EFFORT": " LOW "},
            clear=False,
        ):
            config = ApplicationConfig.from_env()
        self.assertEqual(config.sufficiency_reasoning_effort, "low")

    def test_max_output_tokens_env_override(self) -> None:
        with patch.dict(
            os.environ,
            {"SUFFICIENCY_MAX_OUTPUT_TOKENS": "4096"},
            clear=False,
        ):
            config = ApplicationConfig.from_env()
        self.assertEqual(config.sufficiency_max_output_tokens, 4096)


class SufficiencyProductionCompositionTests(unittest.TestCase):
    def tearDown(self) -> None:
        consume_llm_call_retry_flag()

    def test_factory_passes_application_config_to_semantic_assessor(self) -> None:
        config = ApplicationConfig(
            sufficiency_reasoning_effort="minimal",
            sufficiency_max_output_tokens=8192,
            research_sufficiency_assessor="llm",
        )
        evaluator = build_research_sufficiency_evaluator(
            config=config,
            overrides=ApplicationOverrides(),
            llm_client=Mock(),
        )
        self.assertIsInstance(evaluator, HybridResearchSufficiencyEvaluator)
        assessor = evaluator._semantic
        self.assertIsInstance(assessor, LlmSemanticSufficiencyAssessor)
        generator = assessor._structured_output
        self.assertEqual(generator._reasoning_effort, "minimal")
        self.assertEqual(generator._max_output_tokens, 8192)
        self.assertNotEqual(generator._max_output_tokens, 2048)

    def test_factory_custom_override_propagates(self) -> None:
        config = ApplicationConfig(
            sufficiency_reasoning_effort="low",
            sufficiency_max_output_tokens=4096,
            research_sufficiency_assessor="llm",
        )
        evaluator = build_research_sufficiency_evaluator(
            config=config,
            overrides=ApplicationOverrides(),
            llm_client=Mock(),
        )
        generator = evaluator._semantic._structured_output
        self.assertEqual(generator._reasoning_effort, "low")
        self.assertEqual(generator._max_output_tokens, 4096)

    def test_assessor_passes_generation_options_to_llm_client(self) -> None:
        captured: list[LLMGenerationOptions | None] = []
        mock_llm = Mock()

        def _capture(_prompt, *, options=None):
            captured.append(options)
            return LLMResponse(
                content=json.dumps(_valid_sufficient_payload()),
                finish_reason="stop",
                output_tokens=120,
                max_output_tokens=options.max_output_tokens if options else None,
                configured_reasoning_effort=(
                    options.reasoning_effort if options else None
                ),
            )

        mock_llm.generate.side_effect = _capture
        assessor = LlmSemanticSufficiencyAssessor(
            llm_client=mock_llm,
            max_output_tokens=8192,
            reasoning_effort="minimal",
        )
        rq, need, evidence, signals = _assess_inputs()
        assessor.assess(
            research_question=rq,
            information_need=need,
            evidence=evidence,
            deterministic_signals=signals,
        )
        self.assertEqual(len(captured), 1)
        options = captured[0]
        assert options is not None
        self.assertEqual(options.max_output_tokens, 8192)
        self.assertEqual(options.reasoning_effort, "minimal")

    def test_generator_passes_options_on_each_attempt(self) -> None:
        captured: list[LLMGenerationOptions | None] = []
        mock_llm = Mock()

        def _capture(_prompt, *, options=None):
            captured.append(options)
            if len(captured) == 1:
                return LLMResponse(content="plain prose", finish_reason="stop")
            return LLMResponse(
                content=json.dumps(_valid_sufficient_payload()),
                finish_reason="stop",
            )

        mock_llm.generate.side_effect = _capture
        generator = SufficiencyStructuredOutputGenerator(
            llm_client=mock_llm,
            max_output_tokens=8192,
            reasoning_effort="minimal",
            max_attempts=2,
        )
        generator.generate(Prompt(system="System", user="User"))
        self.assertEqual(mock_llm.generate.call_count, 2)
        self.assertEqual(captured[0].max_output_tokens, 8192)
        self.assertEqual(captured[0].reasoning_effort, "minimal")
        self.assertEqual(captured[1].max_output_tokens, 8192)

    def test_legacy_infrastructure_default_remains_2048_for_direct_use(self) -> None:
        self.assertEqual(DEFAULT_SUFFICIENCY_MAX_OUTPUT_TOKENS, 2048)
        generator = SufficiencyStructuredOutputGenerator(llm_client=Mock())
        self.assertIsNone(generator._max_output_tokens)
        self.assertIsNone(generator._reasoning_effort)

    def test_structured_output_retry_semantics_unchanged(self) -> None:
        mock_llm = Mock()
        inconsistent = json.dumps(
            {
                "status": "sufficient",
                "missing_aspects": [],
                "gap_types": ["insufficient_depth"],
                "search_directives": [],
                "confidence": 0.9,
                "reason": "Invalid.",
            },
        )
        mock_llm.generate.side_effect = [
            LLMResponse(content=inconsistent, finish_reason="stop"),
            LLMResponse(
                content=json.dumps(_valid_sufficient_payload()),
                finish_reason="stop",
            ),
        ]
        assessor = LlmSemanticSufficiencyAssessor(
            llm_client=mock_llm,
            max_output_tokens=8192,
            reasoning_effort="minimal",
            structured_output_max_attempts=2,
        )
        rq, need, evidence, signals = _assess_inputs()
        result = assessor.assess(
            research_question=rq,
            information_need=need,
            evidence=evidence,
            deterministic_signals=signals,
        )
        self.assertEqual(result.status, SufficiencyStatus.SUFFICIENT)
        self.assertEqual(mock_llm.generate.call_count, 2)
        self.assertFalse(semantic_sufficiency_payload_contract(json.loads(inconsistent)))


class OpenAISufficiencyGenerationTests(unittest.TestCase):
    @patch("openai.OpenAI")
    def test_sufficiency_request_sends_configured_reasoning_and_output_tokens(
        self,
        openai_cls,
    ) -> None:
        api_client = Mock()
        openai_cls.return_value = api_client
        api_client.responses.create.return_value = SimpleNamespace(
            status="completed",
            output_text=json.dumps(_valid_sufficient_payload()),
            usage=SimpleNamespace(
                output_tokens=120,
                output_tokens_details=SimpleNamespace(reasoning_tokens=20),
            ),
            incomplete_details=None,
        )

        client = OpenAIClient(LLMConfiguration(model="gpt-5", max_tokens=4096))
        generator = SufficiencyStructuredOutputGenerator(
            llm_client=client,
            max_output_tokens=8192,
            reasoning_effort="minimal",
        )
        generator.generate(Prompt(system="System", user="User"))

        create_kwargs = api_client.responses.create.call_args.kwargs
        self.assertEqual(create_kwargs["reasoning"], {"effort": "minimal"})
        self.assertEqual(create_kwargs["max_output_tokens"], 8192)


if __name__ == "__main__":
    unittest.main()

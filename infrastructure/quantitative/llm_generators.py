"""Single-call production adapters for Quantitative proposal generation."""
from __future__ import annotations

from typing import Any, Mapping

from application.execution.exceptions import BudgetExhaustedError
from application.execution.execution_budget_context import execution_stage_scope
from application.structured_output.json_validator import JsonValidator
from domain.ai.prompt import Prompt
from infrastructure.llm.generation_options import LLMGenerationOptions
from infrastructure.llm.llm_client import LLMClient


class QuantitativeGenerationError(RuntimeError):
    """Sanitized failure raised when no structured proposal was generated."""


class _SingleCallQuantitativeGenerator:
    identity = ""
    stage = ""
    system_prompt = ""

    def __init__(
        self,
        *,
        llm_client: LLMClient,
        json_validator: JsonValidator,
        max_output_tokens: int,
        reasoning_effort: str | None = None,
    ) -> None:
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        self._llm_client = llm_client
        self._json_validator = json_validator
        self._options = LLMGenerationOptions(
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
        )

    def generate(self, prompt: str) -> Mapping[str, Any]:
        if not isinstance(prompt, str) or not prompt.strip():
            raise QuantitativeGenerationError(f"{self.stage} generation input is invalid")
        try:
            with execution_stage_scope(self.stage):
                response = self._llm_client.generate(
                    Prompt(system=self.system_prompt, user=prompt),
                    options=self._options,
                )
        except BudgetExhaustedError:
            raise
        except Exception:
            raise QuantitativeGenerationError(
                f"{self.stage} provider generation failed"
            ) from None

        decoded = self._json_validator.validate(response.content or "")
        if not decoded.is_valid:
            raise QuantitativeGenerationError(
                f"{self.stage} structured response is malformed"
            )
        if not isinstance(decoded.data, Mapping):
            raise QuantitativeGenerationError(
                f"{self.stage} structured response must be an object"
            )
        return dict(decoded.data)


class LLMQuantitativeFindingGenerator(_SingleCallQuantitativeGenerator):
    identity = "quantitative-llm-findings-v1"
    stage = "quant_findings"
    system_prompt = (
        "Return exactly one JSON object containing Quantitative Finding proposals. "
        "Use only the supplied aggregate authorities and never calculate or repair values."
    )


class LLMQuantitativeInsightGenerator(_SingleCallQuantitativeGenerator):
    identity = "quantitative-llm-insights-v1"
    stage = "quant_insights"
    system_prompt = (
        "Return exactly one JSON object containing Quantitative Insight proposals. "
        "Use only the supplied accepted Findings and never add numeric authority."
    )


class LLMQuantitativeReportGenerator(_SingleCallQuantitativeGenerator):
    identity = "quantitative-llm-report-v1"
    stage = "quant_report"
    system_prompt = (
        "Return exactly one JSON object containing the Quantitative Report proposal. "
        "Use only the supplied accepted support chain and never add numeric authority."
    )

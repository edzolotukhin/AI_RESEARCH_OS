from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from application.exceptions.structured_output_error import StructuredOutputError
from application.execution.execution_budget_retry import mark_llm_call_as_retry
from application.research_quality.semantic_sufficiency_contract import (
    SEMANTIC_SUFFICIENCY_PAYLOAD_SCHEMA,
    semantic_sufficiency_payload_contract,
)
from application.structured_output.parser import StructuredOutputParser
from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt
from infrastructure.llm.generation_options import LLMGenerationOptions
from infrastructure.llm.llm_client import LLMClient

DEFAULT_SUFFICIENCY_MAX_OUTPUT_TOKENS = 2048
DEFAULT_SUFFICIENCY_STRUCTURED_OUTPUT_MAX_ATTEMPTS = 3

# Legacy constructor/test default only. Production composition must pass
# ApplicationConfig.sufficiency_max_output_tokens explicitly.

_RESPONSE_PREVIEW_LIMIT = 800


@dataclass(frozen=True)
class SufficiencyGenerationTelemetry:
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    visible_output_length: int | None = None
    finish_reason: str | None = None
    max_output_tokens: int | None = None
    reasoning_effort: str | None = None
    parse_failure_category: str | None = None
    contract_failure_category: str | None = None
    attempts: int = 1


class SufficiencyStructuredOutputGenerator:
    """Bounded structured-output generation with correction retries for sufficiency JSON."""

    DEFAULT_MAX_ATTEMPTS = DEFAULT_SUFFICIENCY_STRUCTURED_OUTPUT_MAX_ATTEMPTS

    def __init__(
        self,
        *,
        llm_client: LLMClient,
        max_output_tokens: int | None = None,
        reasoning_effort: str | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1.")
        self._llm_client = llm_client
        self._parser = StructuredOutputParser()
        self._max_output_tokens = max_output_tokens
        self._reasoning_effort = reasoning_effort
        self._max_attempts = max_attempts
        self._last_telemetry: SufficiencyGenerationTelemetry | None = None

    @property
    def last_telemetry(self) -> SufficiencyGenerationTelemetry | None:
        return self._last_telemetry

    def generate(
        self,
        prompt: Prompt,
        *,
        payload_schema: str = SEMANTIC_SUFFICIENCY_PAYLOAD_SCHEMA,
    ) -> dict[str, Any]:
        current_prompt = prompt
        last_error: StructuredOutputError | None = None
        options = LLMGenerationOptions(
            max_output_tokens=self._max_output_tokens,
            reasoning_effort=self._reasoning_effort,
        )

        for attempt in range(1, self._max_attempts + 1):
            if attempt > 1:
                mark_llm_call_as_retry()
            response = self._llm_client.generate(current_prompt, options=options)
            try:
                payload = self._parser.parse(
                    response.content,
                    candidate_validator=semantic_sufficiency_payload_contract,
                    llm_truncated=response.was_truncated,
                    finish_reason=response.finish_reason,
                    output_tokens=response.output_tokens,
                    max_output_tokens=response.max_output_tokens,
                    reasoning_tokens=response.reasoning_tokens,
                    incomplete_reason=response.incomplete_reason,
                    configured_reasoning_effort=response.configured_reasoning_effort,
                    visible_output_length=response.visible_output_length,
                    reasoning_budget_exhausted=response.reasoning_budget_exhausted,
                )
                self._last_telemetry = SufficiencyGenerationTelemetry(
                    output_tokens=response.output_tokens,
                    reasoning_tokens=response.reasoning_tokens,
                    visible_output_length=response.visible_output_length,
                    finish_reason=response.finish_reason,
                    max_output_tokens=response.max_output_tokens,
                    reasoning_effort=response.configured_reasoning_effort,
                    attempts=attempt,
                )
                return payload
            except StructuredOutputError as exc:
                last_error = exc.with_attempt_context(
                    attempts=attempt,
                    finish_reason=response.finish_reason,
                    output_tokens=response.output_tokens,
                    max_output_tokens=response.max_output_tokens,
                    reasoning_tokens=response.reasoning_tokens,
                    incomplete_reason=response.incomplete_reason,
                    configured_reasoning_effort=response.configured_reasoning_effort,
                    visible_output_length=response.visible_output_length,
                    reasoning_budget_exhausted=response.reasoning_budget_exhausted,
                    is_truncated=exc.is_truncated or response.was_truncated,
                )
                self._last_telemetry = SufficiencyGenerationTelemetry(
                    output_tokens=response.output_tokens,
                    reasoning_tokens=response.reasoning_tokens,
                    visible_output_length=response.visible_output_length,
                    finish_reason=response.finish_reason,
                    max_output_tokens=response.max_output_tokens,
                    reasoning_effort=response.configured_reasoning_effort,
                    parse_failure_category=_parse_failure_category(last_error),
                    contract_failure_category=_contract_failure_category(last_error),
                    attempts=attempt,
                )
                if attempt >= self._max_attempts:
                    raise last_error from exc
                current_prompt = _build_correction_prompt(
                    original_prompt=prompt,
                    invalid_response=response,
                    error=last_error,
                    payload_schema=payload_schema,
                )

        if last_error is not None:
            raise last_error
        raise StructuredOutputError("Semantic sufficiency structured output generation failed.")


def _parse_failure_category(error: StructuredOutputError) -> str:
    if error.is_truncated:
        return "truncated_output"
    return "parse_error"


def _contract_failure_category(error: StructuredOutputError) -> str | None:
    if (error.stage or "").lower() == "contract":
        return "invalid_sufficiency_contract"
    return None


def _build_correction_prompt(
    *,
    original_prompt: Prompt,
    invalid_response: LLMResponse,
    error: StructuredOutputError,
    payload_schema: str,
) -> Prompt:
    preview = (invalid_response.content or "")[:_RESPONSE_PREVIEW_LIMIT]
    compact_note = (
        "Regenerate compact valid JSON only. Keep missing_aspects and "
        "search_directives short and within scope of the InformationNeed."
        if error.is_truncated
        else "Regenerate valid JSON only. Keep output compact."
    )
    user = "\n".join(
        [
            original_prompt.user,
            "CORRECTION REQUEST",
            compact_note,
            "REQUIRED JSON SCHEMA",
            payload_schema,
            "VALIDATION ERROR",
            str(error),
            "INVALID RESPONSE PREVIEW",
            preview,
        ],
    )
    return Prompt(system=original_prompt.system, user=user)

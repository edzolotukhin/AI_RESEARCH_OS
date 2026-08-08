from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from application.exceptions.structured_output_error import StructuredOutputError
from application.execution.execution_budget_retry import mark_llm_call_as_retry
from application.research_quality.raw_semantic_decision_contract import (
    RAW_SEMANTIC_DECISION_PAYLOAD_SCHEMA,
    RawSemanticDecisionContractGate,
    raw_semantic_decision_payload_contract,
    raw_semantic_decision_payload_schema_text,
    render_allowed_aspect_contract,
)
from application.research_quality.semantic_sufficiency_contract import (
    SEMANTIC_SUFFICIENCY_PAYLOAD_SCHEMA,
    semantic_sufficiency_payload_contract,
)
from application.structured_output.parser import StructuredOutputParser
from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt
from infrastructure.llm.generation_options import LLMGenerationOptions
from infrastructure.llm.llm_client import LLMClient

logger = logging.getLogger(__name__)

DEFAULT_SUFFICIENCY_MAX_OUTPUT_TOKENS = 2048
DEFAULT_SUFFICIENCY_STRUCTURED_OUTPUT_MAX_ATTEMPTS = 3

# Legacy constructor/test default only. Production composition must pass
# ApplicationConfig.sufficiency_max_output_tokens explicitly.

_RESPONSE_PREVIEW_LIMIT = 800
_MAX_DIAGNOSTIC_MESSAGE_CHARS = 200


@dataclass(frozen=True)
class StructuredOutputAttemptTelemetry:
    """Bounded diagnostics for one structured-output generation attempt."""

    attempt: int
    success: bool
    stage: str | None = None
    error_type: str | None = None
    finish_reason: str | None = None
    is_truncated: bool | None = None
    reasoning_budget_exhausted: bool | None = None
    parse_failure_category: str | None = None
    structured_output_failure_category: str | None = None
    contract_failure_category: str | None = None
    contract_rejection_code: str | None = None
    allowed_aspect_ids: tuple[str, ...] = ()
    returned_supported_aspects: tuple[str, ...] = ()
    returned_missing_aspects: tuple[str, ...] = ()
    unknown_aspect_ids: tuple[str, ...] = ()
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    max_output_tokens: int | None = None
    visible_output_length: int | None = None
    structured_output_message: str | None = None
    json_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "success": self.success,
            "stage": self.stage,
            "error_type": self.error_type,
            "finish_reason": self.finish_reason,
            "is_truncated": self.is_truncated,
            "reasoning_budget_exhausted": self.reasoning_budget_exhausted,
            "parse_failure_category": self.parse_failure_category,
            "structured_output_failure_category": self.structured_output_failure_category,
            "contract_failure_category": self.contract_failure_category,
            "contract_rejection_code": self.contract_rejection_code,
            "allowed_aspect_ids": list(self.allowed_aspect_ids),
            "returned_supported_aspects": list(self.returned_supported_aspects),
            "returned_missing_aspects": list(self.returned_missing_aspects),
            "unknown_aspect_ids": list(self.unknown_aspect_ids),
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "max_output_tokens": self.max_output_tokens,
            "visible_output_length": self.visible_output_length,
            "structured_output_message": self.structured_output_message,
            "json_error": self.json_error,
        }


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
        self._attempt_history: tuple[StructuredOutputAttemptTelemetry, ...] = ()

    @property
    def last_telemetry(self) -> SufficiencyGenerationTelemetry | None:
        return self._last_telemetry

    @property
    def attempt_history(self) -> tuple[StructuredOutputAttemptTelemetry, ...]:
        return self._attempt_history

    def generate(
        self,
        prompt: Prompt,
        *,
        payload_schema: str = RAW_SEMANTIC_DECISION_PAYLOAD_SCHEMA,
        candidate_validator=raw_semantic_decision_payload_contract,
        allowed_aspect_ids: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        current_prompt = prompt
        last_error: StructuredOutputError | None = None
        attempt_history: list[StructuredOutputAttemptTelemetry] = []
        self._attempt_history = ()
        contract_gate: RawSemanticDecisionContractGate | None = None
        if candidate_validator is raw_semantic_decision_payload_contract:
            contract_gate = RawSemanticDecisionContractGate(
                allowed_aspect_ids=allowed_aspect_ids,
            )
            validator = contract_gate.accepts
        else:
            validator = candidate_validator
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
                    candidate_validator=validator,
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
                attempt_history.append(
                    _success_attempt_record(
                        attempt=attempt,
                        response=response,
                    ),
                )
                self._attempt_history = tuple(attempt_history)
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
                failure_record = _failure_attempt_record(
                    attempt=attempt,
                    error=last_error,
                    response=response,
                    contract_rejection_code=_contract_rejection_code(
                        error=last_error,
                        contract_gate=contract_gate,
                    ),
                    contract_gate=contract_gate,
                    allowed_aspect_ids=allowed_aspect_ids,
                )
                attempt_history.append(failure_record)
                self._attempt_history = tuple(attempt_history)
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
                _log_intermediate_retry(failure_record)
                current_prompt = _build_correction_prompt(
                    original_prompt=prompt,
                    invalid_response=response,
                    error=last_error,
                    payload_schema=payload_schema,
                    allowed_aspect_ids=allowed_aspect_ids,
                )

        if last_error is not None:
            raise last_error
        raise StructuredOutputError("Semantic sufficiency structured output generation failed.")


def _success_attempt_record(
    *,
    attempt: int,
    response: LLMResponse,
) -> StructuredOutputAttemptTelemetry:
    return StructuredOutputAttemptTelemetry(
        attempt=attempt,
        success=True,
        finish_reason=response.finish_reason,
        is_truncated=response.was_truncated,
        reasoning_budget_exhausted=response.reasoning_budget_exhausted,
        output_tokens=response.output_tokens,
        reasoning_tokens=response.reasoning_tokens,
        max_output_tokens=response.max_output_tokens,
        visible_output_length=response.visible_output_length,
    )


def _failure_attempt_record(
    *,
    attempt: int,
    error: StructuredOutputError,
    response: LLMResponse,
    contract_rejection_code: str | None = None,
    contract_gate: RawSemanticDecisionContractGate | None = None,
    allowed_aspect_ids: tuple[str, ...] = (),
) -> StructuredOutputAttemptTelemetry:
    base_message = _bounded_text(_structured_output_base_message(error))
    json_error = _bounded_text(error.json_decode_message) if error.json_decode_message else None
    gate = contract_gate
    return StructuredOutputAttemptTelemetry(
        attempt=attempt,
        success=False,
        stage=error.stage,
        error_type=base_message,
        finish_reason=response.finish_reason,
        is_truncated=error.is_truncated,
        reasoning_budget_exhausted=error.reasoning_budget_exhausted,
        parse_failure_category=_parse_failure_category(error),
        structured_output_failure_category=_structured_output_failure_category(error),
        contract_failure_category=_contract_failure_category(error),
        contract_rejection_code=contract_rejection_code,
        allowed_aspect_ids=allowed_aspect_ids,
        returned_supported_aspects=gate.last_returned_supported_aspects if gate else (),
        returned_missing_aspects=gate.last_returned_missing_aspects if gate else (),
        unknown_aspect_ids=gate.last_unknown_aspect_ids if gate else (),
        output_tokens=response.output_tokens,
        reasoning_tokens=response.reasoning_tokens,
        max_output_tokens=response.max_output_tokens,
        visible_output_length=response.visible_output_length,
        structured_output_message=base_message,
        json_error=json_error,
    )


def _log_intermediate_retry(record: StructuredOutputAttemptTelemetry) -> None:
    logger.warning(
        "sufficiency_structured_output_retry attempt=%s stage=%s is_truncated=%s "
        "parse_failure_category=%s structured_output_failure_category=%s "
        "contract_failure_category=%s contract_rejection_code=%s",
        record.attempt,
        record.stage,
        record.is_truncated,
        record.parse_failure_category,
        record.structured_output_failure_category,
        record.contract_failure_category,
        record.contract_rejection_code,
    )


def _structured_output_base_message(error: StructuredOutputError) -> str:
    text = str(error)
    if " (" in text:
        return text.split(" (", 1)[0]
    return text


def _bounded_text(value: str | None, *, limit: int = _MAX_DIAGNOSTIC_MESSAGE_CHARS) -> str | None:
    if value is None:
        return None
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _parse_failure_category(error: StructuredOutputError) -> str:
    if error.is_truncated:
        return "truncated_output"
    return "parse_error"


def _structured_output_failure_category(error: StructuredOutputError) -> str:
    if error.is_truncated:
        return "truncated_output"
    if (error.stage or "").lower() == "contract":
        return "contract_validation"
    return "syntax_or_extraction"


def _contract_rejection_code(
    *,
    error: StructuredOutputError,
    contract_gate: RawSemanticDecisionContractGate | None,
) -> str | None:
    if (error.stage or "").lower() != "contract":
        return None
    if contract_gate is None:
        return None
    return contract_gate.last_rejection_code


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
    allowed_aspect_ids: tuple[str, ...] = (),
) -> Prompt:
    preview = (invalid_response.content or "")[:_RESPONSE_PREVIEW_LIMIT]
    compact_note = (
        "Regenerate compact valid JSON only. Keep aspect identifiers and reason "
        "short and within scope of the InformationNeed."
        if error.is_truncated
        else "Regenerate valid JSON only. Keep output compact."
    )
    sections = [
        original_prompt.user,
        "CORRECTION REQUEST",
        compact_note,
    ]
    if allowed_aspect_ids:
        sections.extend(
            [
                render_allowed_aspect_contract(allowed_aspect_ids=allowed_aspect_ids),
            ],
        )
    sections.extend(
        [
            "REQUIRED JSON SCHEMA",
            payload_schema or raw_semantic_decision_payload_schema_text(),
            "VALIDATION ERROR",
            str(error),
            "INVALID RESPONSE PREVIEW",
            preview,
        ],
    )
    user = "\n".join(sections)
    return Prompt(system=original_prompt.system, user=user)

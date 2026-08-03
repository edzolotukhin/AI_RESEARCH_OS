from __future__ import annotations

from application.exceptions.structured_output_error import StructuredOutputError
from application.planner.executor_catalog import ExecutorCatalog
from application.structured_output.contracts import StructuredPayloadContract
from application.structured_output.correction_prompt import (
    PLANNER_PAYLOAD_SCHEMA,
    StructuredOutputCorrectionPromptBuilder,
)
from application.structured_output.parser import StructuredOutputParser

from domain.ai.prompt import Prompt
from infrastructure.llm.llm_client import LLMClient


class StructuredOutputGenerator:
    """
    Orchestrates LLM generation with strict structured-output parsing and retry.
    """

    DEFAULT_MAX_ATTEMPTS = 3

    def __init__(
        self,
        llm_client: LLMClient,
        parser: StructuredOutputParser,
        correction_prompt_builder: StructuredOutputCorrectionPromptBuilder | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        payload_schema: str = PLANNER_PAYLOAD_SCHEMA,
        executor_catalog: ExecutorCatalog | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1.")

        self._llm_client = llm_client
        self._parser = parser
        self._correction_prompt_builder = (
            correction_prompt_builder
            or StructuredOutputCorrectionPromptBuilder()
        )
        self._max_attempts = max_attempts
        self._payload_schema = payload_schema
        self._executor_catalog = executor_catalog

    def generate(
        self,
        prompt: Prompt,
        payload_contract: StructuredPayloadContract,
        *,
        payload_schema: str | None = None,
    ) -> dict:
        current_prompt = prompt
        schema = payload_schema or self._payload_schema
        last_error: StructuredOutputError | None = None

        for attempt in range(1, self._max_attempts + 1):
            response = self._llm_client.generate(current_prompt)

            try:
                return self._parser.parse(
                    response.content,
                    payload_contract=payload_contract,
                    llm_truncated=response.was_truncated,
                    finish_reason=response.finish_reason,
                    output_tokens=response.output_tokens,
                    max_output_tokens=response.max_output_tokens,
                )
            except StructuredOutputError as exc:
                enriched_error = exc.with_attempt_context(
                    attempts=attempt,
                    finish_reason=response.finish_reason,
                    output_tokens=response.output_tokens,
                    max_output_tokens=response.max_output_tokens,
                    is_truncated=exc.is_truncated or response.was_truncated,
                )
                last_error = enriched_error

                if attempt >= self._max_attempts:
                    raise enriched_error from exc

                contract_validation_message = getattr(
                    payload_contract,
                    "last_validation_error",
                    "",
                )

                current_prompt = self._correction_prompt_builder.build(
                    original_prompt=prompt,
                    invalid_response=response,
                    error=enriched_error,
                    payload_schema=schema,
                    truncated=enriched_error.is_truncated,
                    allowed_executor_ids=(
                        self._executor_catalog.executor_ids
                        if self._executor_catalog is not None
                        else None
                    ),
                    contract_validation_message=contract_validation_message,
                    planner_bounds=getattr(payload_contract, "bounds", None),
                )

        if last_error is not None:
            raise last_error

        raise StructuredOutputError(
            "Structured output generation failed without a parser error.",
            attempts=self._max_attempts,
        )

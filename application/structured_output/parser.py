from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from application.exceptions.structured_output_error import StructuredOutputError

from .contracts import StructuredPayloadContract
from .json_extractor import JsonExtractor
from .json_repair import JsonRepair
from .json_validator import JsonValidationResult, JsonValidator
from .response_cleaner import ResponseCleaner


@dataclass(frozen=True)
class _CandidateParseResult:
    mapping: Mapping[str, Any] | None
    is_truncated: bool
    validation: JsonValidationResult | None


class StructuredOutputParser:
    """
    Coordinates structured output extraction from raw LLM text.

    LLM -> ResponseCleaner -> JsonExtractor -> JsonValidator
       -> (optional) JsonRepair -> JsonValidator -> payload contract
    """

    def __init__(
        self,
        cleaner: ResponseCleaner | None = None,
        extractor: JsonExtractor | None = None,
        validator: JsonValidator | None = None,
        repair: JsonRepair | None = None,
    ) -> None:
        self._cleaner = cleaner or ResponseCleaner()
        self._extractor = extractor or JsonExtractor()
        self._validator = validator or JsonValidator()
        self._repair = repair or JsonRepair()

    def parse(
        self,
        raw_text: str,
        payload_contract: StructuredPayloadContract | None = None,
        candidate_validator: Callable[[Mapping[str, Any]], bool] | None = None,
        *,
        llm_truncated: bool = False,
        finish_reason: str | None = None,
        output_tokens: int | None = None,
        max_output_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        incomplete_reason: str | None = None,
        configured_reasoning_effort: str | None = None,
        visible_output_length: int | None = None,
        reasoning_budget_exhausted: bool = False,
    ) -> dict[str, Any]:
        cleaned = self._cleaner.clean(raw_text)

        if not cleaned.strip():
            raise StructuredOutputError(
                "LLM response is empty after cleaning.",
                stage="clean",
                source_preview=self._preview(raw_text),
                is_truncated=llm_truncated,
                finish_reason=finish_reason,
                output_tokens=output_tokens,
                max_output_tokens=max_output_tokens,
                reasoning_tokens=reasoning_tokens,
                incomplete_reason=incomplete_reason,
                configured_reasoning_effort=configured_reasoning_effort,
                visible_output_length=visible_output_length,
                reasoning_budget_exhausted=reasoning_budget_exhausted,
            )

        candidates = self._extractor.extract_all(cleaned)

        if not candidates:
            raise StructuredOutputError(
                "LLM response does not contain JSON candidates.",
                stage="extract",
                candidate_count=0,
                source_preview=self._preview(cleaned),
                is_truncated=llm_truncated,
                finish_reason=finish_reason,
                output_tokens=output_tokens,
                max_output_tokens=max_output_tokens,
                reasoning_tokens=reasoning_tokens,
                incomplete_reason=incomplete_reason,
                configured_reasoning_effort=configured_reasoning_effort,
                visible_output_length=visible_output_length,
                reasoning_budget_exhausted=reasoning_budget_exhausted,
            )

        parse_results = [
            self._parse_candidate_to_mapping(candidate)
            for candidate in candidates
        ]

        syntax_valid_mappings = [
            result.mapping
            for result in parse_results
            if result.mapping is not None
        ]

        contract_checker = self._resolve_contract_checker(
            payload_contract,
            candidate_validator,
        )

        contract_valid_mappings = [
            mapping
            for mapping in syntax_valid_mappings
            if contract_checker(mapping)
        ]

        if contract_valid_mappings:
            return dict(contract_valid_mappings[-1])

        if syntax_valid_mappings and contract_checker is not self._accept_all:
            raise StructuredOutputError(
                "No JSON candidate satisfies the payload contract.",
                stage="contract",
                candidate_count=len(candidates),
                syntax_valid_count=len(syntax_valid_mappings),
                contract_valid_count=0,
                source_preview=self._preview(cleaned),
                is_truncated=self._resolve_truncated(
                    llm_truncated,
                    parse_results,
                ),
                finish_reason=finish_reason,
                output_tokens=output_tokens,
                max_output_tokens=max_output_tokens,
                reasoning_tokens=reasoning_tokens,
                incomplete_reason=incomplete_reason,
                configured_reasoning_effort=configured_reasoning_effort,
                visible_output_length=visible_output_length,
                reasoning_budget_exhausted=reasoning_budget_exhausted,
            )

        first_candidate = candidates[0]
        first_result = parse_results[0]
        validation = first_result.validation

        raise StructuredOutputError(
            "LLM response does not contain a syntactically valid JSON object.",
            stage="validate",
            candidate_count=len(candidates),
            syntax_valid_count=0,
            contract_valid_count=0,
            source_preview=self._preview(cleaned),
            candidate_preview=self._preview(first_candidate),
            candidate_length=len(first_candidate),
            json_decode_message=validation.error if validation else "",
            json_error_line=validation.error_line if validation else None,
            json_error_column=validation.error_column if validation else None,
            json_error_position=validation.error_position if validation else None,
            is_truncated=self._resolve_truncated(
                llm_truncated,
                parse_results,
            ),
            finish_reason=finish_reason,
            output_tokens=output_tokens,
            max_output_tokens=max_output_tokens,
            reasoning_tokens=reasoning_tokens,
            incomplete_reason=incomplete_reason,
            configured_reasoning_effort=configured_reasoning_effort,
            visible_output_length=visible_output_length,
            reasoning_budget_exhausted=reasoning_budget_exhausted,
        )

    def _parse_candidate_to_mapping(
        self,
        candidate: str,
    ) -> _CandidateParseResult:
        validation = self._validator.validate(candidate)

        if validation.is_valid:
            mapping = self._as_mapping(validation.data)

            return _CandidateParseResult(
                mapping=mapping,
                is_truncated=False,
                validation=validation,
            )

        repair_result = self._repair.try_repair(candidate)

        if (
            repair_result.has_unclosed_string
            or repair_result.has_unclosed_container
        ):
            return _CandidateParseResult(
                mapping=None,
                is_truncated=True,
                validation=validation,
            )

        repaired_validation = self._validator.validate(
            repair_result.text,
        )

        if not repaired_validation.is_valid:
            return _CandidateParseResult(
                mapping=None,
                is_truncated=False,
                validation=validation,
            )

        return _CandidateParseResult(
            mapping=self._as_mapping(repaired_validation.data),
            is_truncated=False,
            validation=repaired_validation,
        )

    @staticmethod
    def _resolve_truncated(
        llm_truncated: bool,
        parse_results: list[_CandidateParseResult],
    ) -> bool:
        if llm_truncated:
            return True

        return any(result.is_truncated for result in parse_results)

    @staticmethod
    def _as_mapping(
        data: Any,
    ) -> Mapping[str, Any] | None:
        if isinstance(data, Mapping):
            return data

        return None

    @staticmethod
    def _resolve_contract_checker(
        payload_contract: StructuredPayloadContract | None,
        candidate_validator: Callable[[Mapping[str, Any]], bool] | None,
    ) -> Callable[[Mapping[str, Any]], bool]:
        if candidate_validator is not None:
            return candidate_validator

        if payload_contract is not None:
            return payload_contract.accepts

        return StructuredOutputParser._accept_all

    @staticmethod
    def _accept_all(
        payload: Mapping[str, Any],
    ) -> bool:
        return True

    @staticmethod
    def _preview(
        text: str,
        limit: int = 120,
    ) -> str:
        compact = " ".join(text.split())

        if len(compact) <= limit:
            return compact

        return compact[: limit - 3] + "..."

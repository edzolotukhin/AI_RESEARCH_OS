from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from application.exceptions.structured_output_error import StructuredOutputError

from .contracts import StructuredPayloadContract
from .json_extractor import JsonExtractor
from .json_repair import JsonRepair
from .json_validator import JsonValidator
from .response_cleaner import ResponseCleaner


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
    ) -> dict[str, Any]:
        cleaned = self._cleaner.clean(raw_text)

        if not cleaned.strip():
            raise StructuredOutputError(
                "LLM response is empty after cleaning.",
                stage="clean",
                source_preview=self._preview(raw_text),
            )

        candidates = self._extractor.extract_all(cleaned)

        if not candidates:
            raise StructuredOutputError(
                "LLM response does not contain JSON candidates.",
                stage="extract",
                candidate_count=0,
                source_preview=self._preview(cleaned),
            )

        syntax_valid_mappings = self._collect_syntax_valid_mappings(
            candidates,
        )

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
            )

        raise StructuredOutputError(
            "LLM response does not contain a syntactically valid JSON object.",
            stage="validate",
            candidate_count=len(candidates),
            syntax_valid_count=0,
            contract_valid_count=0,
            source_preview=self._preview(cleaned),
        )

    def _collect_syntax_valid_mappings(
        self,
        candidates: list[str],
    ) -> list[Mapping[str, Any]]:
        syntax_valid_mappings: list[Mapping[str, Any]] = []

        for candidate in candidates:
            mapping = self._parse_candidate_to_mapping(candidate)
            if mapping is not None:
                syntax_valid_mappings.append(mapping)

        return syntax_valid_mappings

    def _parse_candidate_to_mapping(
        self,
        candidate: str,
    ) -> Mapping[str, Any] | None:
        validation = self._validator.validate(candidate)

        if validation.is_valid:
            return self._as_mapping(validation.data)

        repair_result = self._repair.try_repair(candidate)

        if (
            repair_result.has_unclosed_string
            or repair_result.has_unclosed_container
        ):
            return None

        repaired_validation = self._validator.validate(
            repair_result.text,
        )

        if not repaired_validation.is_valid:
            return None

        return self._as_mapping(repaired_validation.data)

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

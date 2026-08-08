from __future__ import annotations

from enum import Enum
from typing import Any

from domain.ai.llm_response import LLMResponse

from application.structured_output.json_extractor import JsonExtractor
from application.structured_output.json_validator import JsonValidator


class EvidenceResponseClassification(str, Enum):
    """Provider-neutral Evidence LLM response outcome taxonomy."""

    EMPTY_PROVIDER_OUTPUT = "empty_provider_output"
    INCOMPLETE_PROVIDER_OUTPUT = "incomplete_provider_output"
    INVALID_JSON = "invalid_json"
    ROOT_TYPE_MISMATCH = "root_type_mismatch"
    SCHEMA_CONTRACT_MISMATCH = "schema_contract_mismatch"
    VALID_EMPTY_RESULT = "valid_empty_result"
    VALID_CANDIDATES = "valid_candidates"


FAILURE_RESPONSE_CLASSIFICATIONS = frozenset(
    {
        EvidenceResponseClassification.EMPTY_PROVIDER_OUTPUT,
        EvidenceResponseClassification.INCOMPLETE_PROVIDER_OUTPUT,
        EvidenceResponseClassification.INVALID_JSON,
        EvidenceResponseClassification.ROOT_TYPE_MISMATCH,
        EvidenceResponseClassification.SCHEMA_CONTRACT_MISMATCH,
    },
)


def is_incomplete_provider_completion(response: LLMResponse) -> bool:
    return response.was_truncated or response.incomplete_reason is not None


def classify_evidence_llm_response(
    response: LLMResponse,
    *,
    json_extractor: JsonExtractor,
    json_validator: JsonValidator,
) -> tuple[EvidenceResponseClassification, dict[str, Any] | None]:
    """
    Deterministically classify an Evidence LLM response.

    Returns the classification and a parsed root object when the provider
    completion is usable and the root JSON object was extracted. The payload
    may still violate the Evidence schema contract.
    """
    if is_incomplete_provider_completion(response):
        return EvidenceResponseClassification.INCOMPLETE_PROVIDER_OUTPUT, None

    content = response.content or ""
    if len(content) == 0:
        return EvidenceResponseClassification.EMPTY_PROVIDER_OUTPUT, None

    containers = json_extractor.extract_all(content)
    valid_values: list[Any] = []
    for candidate in containers:
        validation = json_validator.validate(candidate)
        if validation.is_valid:
            valid_values.append(validation.data)

    if not valid_values:
        stripped = content.strip()
        if stripped:
            fallback = json_validator.validate(stripped)
            if fallback.is_valid:
                valid_values.append(fallback.data)
        if not valid_values:
            return EvidenceResponseClassification.INVALID_JSON, None

    root_object: dict[str, Any] | None = None
    for value in valid_values:
        if isinstance(value, dict):
            root_object = value
            break

    if root_object is None:
        return EvidenceResponseClassification.ROOT_TYPE_MISMATCH, None

    if "items" not in root_object:
        return EvidenceResponseClassification.SCHEMA_CONTRACT_MISMATCH, root_object

    items_value = root_object["items"]
    if items_value is None:
        return EvidenceResponseClassification.SCHEMA_CONTRACT_MISMATCH, root_object

    if not isinstance(items_value, list):
        return EvidenceResponseClassification.SCHEMA_CONTRACT_MISMATCH, root_object

    if len(items_value) == 0:
        return EvidenceResponseClassification.VALID_EMPTY_RESULT, root_object

    return EvidenceResponseClassification.VALID_CANDIDATES, root_object

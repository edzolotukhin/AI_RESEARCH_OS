from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from application.structured_output.json_extractor import JsonExtractor
from application.structured_output.json_validator import JsonValidator

DEFAULT_RESPONSE_PREVIEW_MAX_LENGTH = 800
MAX_PARSED_ROOT_KEYS = 20
MAX_ITEM_OUTCOMES = 50


def classify_json_value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def build_bounded_response_preview(
    content: str,
    *,
    max_length: int = DEFAULT_RESPONSE_PREVIEW_MAX_LENGTH,
) -> tuple[str, bool]:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = "".join(
        char if char.isprintable() or char in "\n\t" else " "
        for char in normalized
    )
    if len(cleaned) <= max_length:
        return cleaned, False
    return cleaned[:max_length] + "…", True


@dataclass
class ItemFilterOutcome:
    item_index: int
    outcome: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_index": self.item_index,
            "outcome": self.outcome,
        }


@dataclass
class ResponseShapeDiagnostics:
    provider_response_received: bool = False
    response_text_length: int = 0
    response_preview: str = ""
    response_preview_truncated: bool = False
    json_container_count: int = 0
    parsed_root_type: str | None = None
    parsed_root_keys: list[str] = field(default_factory=list)
    container_root_types: list[str] = field(default_factory=list)
    expected_items_key_present: bool = False
    items_value_type: str | None = None
    items_count_pre_filter: int | None = None
    items_count_post_filter: int = 0
    rejected_non_object_item: int = 0
    rejected_missing_information_need_id: int = 0
    rejected_unknown_information_need_id: int = 0
    rejected_empty_statement: int = 0
    rejected_empty_source_excerpt: int = 0
    rejected_invalid_confidence: int = 0
    rejected_candidate_construction_error: int = 0
    item_outcomes: list[ItemFilterOutcome] = field(default_factory=list)
    parser_succeeded: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "provider_response_received": self.provider_response_received,
            "response_text_length": self.response_text_length,
            "response_preview": self.response_preview,
            "response_preview_truncated": self.response_preview_truncated,
            "json_container_count": self.json_container_count,
            "container_root_types": list(self.container_root_types),
            "expected_items_key_present": self.expected_items_key_present,
            "items_count_post_filter": self.items_count_post_filter,
            "rejected_non_object_item": self.rejected_non_object_item,
            "rejected_missing_information_need_id": self.rejected_missing_information_need_id,
            "rejected_unknown_information_need_id": self.rejected_unknown_information_need_id,
            "rejected_empty_statement": self.rejected_empty_statement,
            "rejected_empty_source_excerpt": self.rejected_empty_source_excerpt,
            "rejected_invalid_confidence": self.rejected_invalid_confidence,
            "rejected_candidate_construction_error": self.rejected_candidate_construction_error,
            "parser_succeeded": self.parser_succeeded,
        }
        if self.parsed_root_type is not None:
            payload["parsed_root_type"] = self.parsed_root_type
        if self.parsed_root_keys:
            payload["parsed_root_keys"] = list(self.parsed_root_keys)
        if self.items_value_type is not None:
            payload["items_value_type"] = self.items_value_type
        if self.items_count_pre_filter is not None:
            payload["items_count_pre_filter"] = self.items_count_pre_filter
        if self.item_outcomes:
            payload["item_outcomes"] = [item.to_dict() for item in self.item_outcomes]
        return payload

    @classmethod
    def from_response_content(
        cls,
        content: str,
        *,
        json_extractor: JsonExtractor,
        json_validator: JsonValidator,
        preview_max_length: int = DEFAULT_RESPONSE_PREVIEW_MAX_LENGTH,
    ) -> ResponseShapeDiagnostics:
        preview, truncated = build_bounded_response_preview(
            content,
            max_length=preview_max_length,
        )
        diagnostics = cls(
            provider_response_received=True,
            response_text_length=len(content),
            response_preview=preview,
            response_preview_truncated=truncated,
        )
        containers = json_extractor.extract_all(content)
        diagnostics.json_container_count = len(containers)
        container_root_types: list[str] = []
        for candidate in containers:
            validation = json_validator.validate(candidate)
            if validation.is_valid:
                container_root_types.append(classify_json_value_type(validation.data))
        diagnostics.container_root_types = container_root_types
        if container_root_types:
            diagnostics.parsed_root_type = container_root_types[0]
        else:
            fallback_type = cls._classify_fallback_root_type(content, json_validator)
            diagnostics.parsed_root_type = fallback_type
            if fallback_type != "no_valid_json":
                diagnostics.container_root_types = [fallback_type]
        return diagnostics

    @staticmethod
    def _classify_fallback_root_type(content: str, json_validator: JsonValidator) -> str:
        stripped = content.strip()
        if not stripped:
            return "no_valid_json"
        validation = json_validator.validate(stripped)
        if validation.is_valid:
            return classify_json_value_type(validation.data)
        return "no_valid_json"

    def record_object_root(self, payload: dict[str, Any]) -> None:
        self.parser_succeeded = True
        self.parsed_root_type = "object"
        self.parsed_root_keys = sorted(payload.keys())[:MAX_PARSED_ROOT_KEYS]
        self.expected_items_key_present = "items" in payload
        if "items" not in payload:
            self.items_value_type = "missing"
            self.items_count_pre_filter = 0
            return
        items_value = payload["items"]
        self.items_value_type = classify_json_value_type(items_value)
        if isinstance(items_value, list):
            self.items_count_pre_filter = len(items_value)

    def record_item_rejection(self, *, item_index: int, outcome: str) -> None:
        if outcome == "rejected_non_object_item":
            self.rejected_non_object_item += 1
        elif outcome == "rejected_missing_information_need_id":
            self.rejected_missing_information_need_id += 1
        elif outcome == "rejected_unknown_information_need_id":
            self.rejected_unknown_information_need_id += 1
        elif outcome == "rejected_empty_statement":
            self.rejected_empty_statement += 1
        elif outcome == "rejected_empty_source_excerpt":
            self.rejected_empty_source_excerpt += 1
        elif outcome == "rejected_invalid_confidence":
            self.rejected_invalid_confidence += 1
        elif outcome == "rejected_candidate_construction_error":
            self.rejected_candidate_construction_error += 1
        if len(self.item_outcomes) < MAX_ITEM_OUTCOMES:
            self.item_outcomes.append(ItemFilterOutcome(item_index=item_index, outcome=outcome))


_current_response_shape: ContextVar[ResponseShapeDiagnostics | None] = ContextVar(
    "evidence_extractor_response_shape",
    default=None,
)


def publish_response_shape(diagnostics: ResponseShapeDiagnostics | None) -> None:
    _current_response_shape.set(diagnostics)


def consume_response_shape() -> ResponseShapeDiagnostics | None:
    diagnostics = _current_response_shape.get()
    _current_response_shape.set(None)
    return diagnostics


def reset_response_shape() -> None:
    _current_response_shape.set(None)

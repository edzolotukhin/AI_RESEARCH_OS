from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SufficiencyFailureDiagnostics:
    structured_output_message: str
    stage: str
    is_truncated: bool
    attempts: int
    finish_reason: str | None = None
    output_tokens: int | None = None
    max_output_tokens: int | None = None
    reasoning_tokens: int | None = None
    visible_output_length: int | None = None
    parse_failure_category: str | None = None
    contract_failure_category: str | None = None
    contract_rejection_code: str | None = None
    information_need_id: str | None = None
    allowed_aspect_ids: tuple[str, ...] = ()
    returned_supported_aspects: tuple[str, ...] = ()
    returned_missing_aspects: tuple[str, ...] = ()
    unknown_aspect_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "structured_output_message": self.structured_output_message,
            "stage": self.stage,
            "is_truncated": self.is_truncated,
            "attempts": self.attempts,
            "finish_reason": self.finish_reason,
            "output_tokens": self.output_tokens,
            "max_output_tokens": self.max_output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "visible_output_length": self.visible_output_length,
            "parse_failure_category": self.parse_failure_category,
            "contract_failure_category": self.contract_failure_category,
        }
        if self.contract_rejection_code is not None:
            payload["contract_rejection_code"] = self.contract_rejection_code
        if self.information_need_id is not None:
            payload["information_need_id"] = self.information_need_id
        if self.allowed_aspect_ids:
            payload["allowed_aspect_ids"] = list(self.allowed_aspect_ids)
        if self.returned_supported_aspects:
            payload["returned_supported_aspects"] = list(self.returned_supported_aspects)
        if self.returned_missing_aspects:
            payload["returned_missing_aspects"] = list(self.returned_missing_aspects)
        if self.unknown_aspect_ids:
            payload["unknown_aspect_ids"] = list(self.unknown_aspect_ids)
        return payload


def format_sufficiency_failure_message(
    diagnostics: SufficiencyFailureDiagnostics,
) -> str:
    payload = diagnostics.to_dict()
    return (
        "Semantic sufficiency structured output failed; "
        f"structured_output_message={payload['structured_output_message']!r} "
        f"stage={payload['stage']} "
        f"is_truncated={payload['is_truncated']} "
        f"attempts={payload['attempts']} "
        f"finish_reason={payload['finish_reason']} "
        f"output_tokens={payload['output_tokens']} "
        f"max_output_tokens={payload['max_output_tokens']} "
        f"reasoning_tokens={payload['reasoning_tokens']} "
        f"visible_output_length={payload['visible_output_length']} "
        f"parse_failure_category={payload['parse_failure_category']} "
        f"contract_failure_category={payload['contract_failure_category']} "
        f"contract_rejection_code={payload.get('contract_rejection_code')} "
        f"information_need_id={payload.get('information_need_id')} "
        f"allowed_aspect_ids={payload.get('allowed_aspect_ids')} "
        f"unknown_aspect_ids={payload.get('unknown_aspect_ids')}"
    )

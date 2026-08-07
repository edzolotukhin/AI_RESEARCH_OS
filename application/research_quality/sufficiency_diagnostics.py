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

    def to_dict(self) -> dict[str, Any]:
        return {
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
        f"contract_failure_category={payload['contract_failure_category']}"
    )

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

FAILURE_CATEGORY_PARSE_ERROR = "parse_error"
FAILURE_CATEGORY_LLM_ERROR = "llm_error"
FAILURE_CATEGORY_TRUNCATED_OUTPUT = "truncated_output"
FAILURE_CATEGORY_CONTRACT_ERROR = "contract_error"

CONTRACT_FAILURE_INVALID_REVIEW_CONTRACT = "invalid_review_contract"


@dataclass
class ReviewSectionDiagnostics:
    section_id: str | None
    section_index: int | None = None
    candidate_review_count: int = 0
    parse_failure_category: str | None = None
    contract_failure_category: str | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    visible_output_length: int | None = None
    finish_reason: str | None = None
    max_output_tokens: int | None = None
    reasoning_effort: str | None = None
    attempts: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "section_index": self.section_index,
            "candidate_review_count": self.candidate_review_count,
            "parse_failure_category": self.parse_failure_category,
            "contract_failure_category": self.contract_failure_category,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "visible_output_length": self.visible_output_length,
            "finish_reason": self.finish_reason,
            "max_output_tokens": self.max_output_tokens,
            "reasoning_effort": self.reasoning_effort,
            "attempts": self.attempts,
        }


@dataclass
class ReviewFailureDiagnostics:
    workflow_run_id: str
    section_count: int
    section_failures: int = 0
    sections: list[ReviewSectionDiagnostics] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_run_id": self.workflow_run_id,
            "section_count": self.section_count,
            "section_failures": self.section_failures,
            "sections": [section.to_dict() for section in self.sections],
        }


def format_review_parse_failure_message(diagnostics: ReviewFailureDiagnostics) -> str:
    summary = diagnostics.to_dict()
    last = summary["sections"][-1] if summary["sections"] else {}
    return (
        f"LLM semantic review failed structured output validation for run "
        f"{diagnostics.workflow_run_id}; "
        f"section_count={summary['section_count']} "
        f"section_failures={summary['section_failures']} "
        f"parse_failure_category={last.get('parse_failure_category')} "
        f"contract_failure_category={last.get('contract_failure_category')} "
        f"finish_reason={last.get('finish_reason')} "
        f"output_tokens={last.get('output_tokens')} "
        f"reasoning_tokens={last.get('reasoning_tokens')} "
        f"visible_output_length={last.get('visible_output_length')} "
        f"max_output_tokens={last.get('max_output_tokens')} "
        f"reasoning_effort={last.get('reasoning_effort')}"
    )

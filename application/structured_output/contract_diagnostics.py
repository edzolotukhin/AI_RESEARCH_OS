from __future__ import annotations

import re


GENERIC_CONTRACT_DIAGNOSTIC_CODE = "planner_payload_contract_invalid"
GENERIC_CONTRACT_DIAGNOSTIC_REASON = "planner payload failed the contract"

_KNOWN_PATTERNS = (
    (r"duplicate research question id", "duplicate_research_question_id", "duplicate research question id"),
    (r"duplicate information need id", "duplicate_information_need_id", "duplicate information need id"),
    (r"references unknown question", "information_need_question_reference_invalid", "information need references an unknown research question"),
    (r"research_questions count .* exceeds maximum", "research_questions_limit_exceeded", "research questions exceed the configured planner bound"),
    (r"information_needs count .* exceeds maximum", "information_needs_limit_exceeded", "information needs exceed the configured planner bound"),
    (r"source_strategy count .* exceeds maximum", "source_strategy_limit_exceeded", "source strategies exceed the configured planner bound"),
    (r"analysis_plan count .* exceeds maximum", "analysis_plan_limit_exceeded", "analysis plan exceeds the configured planner bound"),
    (r"deliverable_plan count .* exceeds maximum", "deliverable_plan_limit_exceeded", "deliverable plan exceeds the configured planner bound"),
    (r"assumptions count .* exceeds maximum", "assumptions_limit_exceeded", "assumptions exceed the configured planner bound"),
    (r"limitations count .* exceeds maximum", "limitations_limit_exceeded", "limitations exceed the configured planner bound"),
)


def classify_contract_validation_error(message: object) -> tuple[str, str]:
    """Return a fixed code and non-content reason safe for durable audit."""
    text = str(message or "").lower()
    for pattern, code, safe_reason in _KNOWN_PATTERNS:
        if re.search(pattern, text):
            return code, safe_reason
    return GENERIC_CONTRACT_DIAGNOSTIC_CODE, GENERIC_CONTRACT_DIAGNOSTIC_REASON

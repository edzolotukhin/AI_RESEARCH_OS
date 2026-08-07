from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from domain.research_quality.raw_semantic_decision import RawSemanticDecision

DEFAULT_RAW_SEMANTIC_MAX_ASPECTS = 8
DEFAULT_RAW_SEMANTIC_MAX_CONFLICTS = 8
DEFAULT_RAW_SEMANTIC_MAX_STRING_CHARS = 200
DEFAULT_RAW_SEMANTIC_MAX_REASON_CHARS = 500

_FORBIDDEN_POLICY_FIELDS = frozenset(
    {
        "status",
        "gap_types",
        "search_directives",
        "blocking",
        "ready_for_analysis",
        "coverage",
    },
)

RAW_SEMANTIC_DECISION_PAYLOAD_SCHEMA = """
{
  "supported_aspects": [],
  "missing_aspects": [],
  "semantic_conflicts": [],
  "confidence": 0.85,
  "reason": "string"
}
""".strip()


def raw_semantic_decision_payload_contract(payload: Mapping[str, Any]) -> bool:
    if any(field in payload for field in _FORBIDDEN_POLICY_FIELDS):
        return False

    supported_aspects = payload.get("supported_aspects")
    if not isinstance(supported_aspects, list):
        return False
    if len(supported_aspects) > DEFAULT_RAW_SEMANTIC_MAX_ASPECTS:
        return False
    if not _valid_aspect_list(supported_aspects):
        return False

    missing_aspects = payload.get("missing_aspects")
    if not isinstance(missing_aspects, list):
        return False
    if len(missing_aspects) > DEFAULT_RAW_SEMANTIC_MAX_ASPECTS:
        return False
    if not _valid_aspect_list(missing_aspects):
        return False

    semantic_conflicts = payload.get("semantic_conflicts")
    if not isinstance(semantic_conflicts, list):
        return False
    if len(semantic_conflicts) > DEFAULT_RAW_SEMANTIC_MAX_CONFLICTS:
        return False
    if not _valid_aspect_list(semantic_conflicts):
        return False

    confidence = payload.get("confidence")
    if not isinstance(confidence, (int, float)):
        return False
    if not 0.0 <= float(confidence) <= 1.0:
        return False

    reason = payload.get("reason")
    if not isinstance(reason, str):
        return False
    if not reason.strip() or len(reason) > DEFAULT_RAW_SEMANTIC_MAX_REASON_CHARS:
        return False

    overlap = {
        str(item).strip()
        for item in supported_aspects
        if str(item).strip()
    } & {
        str(item).strip()
        for item in missing_aspects
        if str(item).strip()
    }
    return not overlap


def raw_semantic_decision_from_payload(payload: Mapping[str, Any]) -> RawSemanticDecision:
    return RawSemanticDecision.from_dict(dict(payload))


def _valid_aspect_list(values: list[Any]) -> bool:
    return all(
        isinstance(item, str)
        and 0 < len(item.strip()) <= DEFAULT_RAW_SEMANTIC_MAX_STRING_CHARS
        for item in values
    )

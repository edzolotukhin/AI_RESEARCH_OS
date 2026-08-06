from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from domain.research_quality.gap_type import GapType
from domain.research_quality.sufficiency_status import SufficiencyStatus

DEFAULT_SUFFICIENCY_MAX_MISSING_ASPECTS = 8
DEFAULT_SUFFICIENCY_MAX_SEARCH_DIRECTIVES = 5
DEFAULT_SUFFICIENCY_MAX_STRING_CHARS = 200
DEFAULT_SUFFICIENCY_MAX_REASON_CHARS = 500

_VALID_STATUSES = {member.value for member in SufficiencyStatus}
_VALID_GAP_TYPES = {member.value for member in GapType}

SEMANTIC_SUFFICIENCY_PAYLOAD_SCHEMA = """
{
  "status": "sufficient",
  "missing_aspects": ["string"],
  "gap_types": ["insufficient_depth"],
  "search_directives": ["string"],
  "confidence": 0.85,
  "reason": "string"
}
""".strip()


def semantic_sufficiency_payload_contract(payload: Mapping[str, Any]) -> bool:
    status = payload.get("status")
    if status not in _VALID_STATUSES:
        return False

    missing_aspects = payload.get("missing_aspects")
    if not isinstance(missing_aspects, list):
        return False
    if len(missing_aspects) > DEFAULT_SUFFICIENCY_MAX_MISSING_ASPECTS:
        return False
    if not all(
        isinstance(item, str)
        and 0 < len(item.strip()) <= DEFAULT_SUFFICIENCY_MAX_STRING_CHARS
        for item in missing_aspects
    ):
        return False

    gap_types = payload.get("gap_types")
    if not isinstance(gap_types, list):
        return False
    if len(gap_types) > len(GapType):
        return False
    if not all(isinstance(item, str) and item in _VALID_GAP_TYPES for item in gap_types):
        return False

    search_directives = payload.get("search_directives")
    if not isinstance(search_directives, list):
        return False
    if len(search_directives) > DEFAULT_SUFFICIENCY_MAX_SEARCH_DIRECTIVES:
        return False
    if not all(
        isinstance(item, str)
        and 0 < len(item.strip()) <= DEFAULT_SUFFICIENCY_MAX_STRING_CHARS
        for item in search_directives
    ):
        return False

    confidence = payload.get("confidence")
    if confidence is not None:
        if not isinstance(confidence, (int, float)):
            return False
        if not 0.0 <= float(confidence) <= 1.0:
            return False

    reason = payload.get("reason")
    if not isinstance(reason, str):
        return False
    if not reason.strip() or len(reason) > DEFAULT_SUFFICIENCY_MAX_REASON_CHARS:
        return False

    return True

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from domain.research_quality.raw_semantic_decision import RawSemanticDecision
from domain.research_quality.semantic_decision_normalizer import (
    LEGACY_NEED_ASPECT_ID,
    UNRESOLVABLE_CONFLICT_ID,
)

DEFAULT_RAW_SEMANTIC_MAX_ASPECTS = 8
DEFAULT_RAW_SEMANTIC_MAX_CONFLICTS = 8
DEFAULT_RAW_SEMANTIC_MAX_STRING_CHARS = 200
DEFAULT_RAW_SEMANTIC_MAX_REASON_CHARS = 500

FORBIDDEN_RAW_SEMANTIC_POLICY_FIELDS: frozenset[str] = frozenset(
    {
        "status",
        "gap_types",
        "search_directives",
        "blocking",
        "ready_for_analysis",
        "coverage",
    },
)

_REQUIRED_RAW_SEMANTIC_FIELDS: tuple[str, ...] = (
    "supported_aspects",
    "missing_aspects",
    "semantic_conflicts",
    "confidence",
    "reason",
)

RAW_SEMANTIC_DECISION_PAYLOAD_SCHEMA = """
{
  "supported_aspects": ["string"],
  "missing_aspects": ["string"],
  "semantic_conflicts": ["string"],
  "confidence": 0.0,
  "reason": "string"
}
""".strip()


def raw_semantic_decision_payload_schema_text() -> str:
    """Authoritative RawSemanticDecision JSON shape for LLM prompts."""
    return RAW_SEMANTIC_DECISION_PAYLOAD_SCHEMA


def raw_semantic_decision_output_instructions() -> str:
    """Bounded output-contract instructions shared by first-pass and correction prompts."""
    forbidden = ", ".join(sorted(FORBIDDEN_RAW_SEMANTIC_POLICY_FIELDS))
    return "\n".join(
        [
            "OUTPUT CONTRACT (RawSemanticDecision JSON only):",
            "Return one JSON object with exactly these five keys and no others:",
            "supported_aspects, missing_aspects, semantic_conflicts, confidence, reason.",
            "",
            "Field semantics:",
            "- supported_aspects: array of canonical aspect identifiers supported by evidence.",
            "- missing_aspects: array of canonical required aspect identifiers not supported.",
            "- semantic_conflicts: array of identifiers for substantive contradictions "
            "between evidence items only (conflicting claims supported by different evidence).",
            "- Use semantic_conflicts=[] when evidence is absent, shallow, incomplete, or "
            "does not yet answer the InformationNeed.",
            "- Lack of supporting evidence is NOT a semantic conflict; express it via "
            "missing_aspects.",
            "- Do NOT output \"unresolvable\" merely because current evidence is insufficient.",
            "- Absence from the current Evidence set does not establish that future research "
            "cannot resolve the need.",
            "- Output \"unresolvable\" in semantic_conflicts ONLY when available evidence "
            "substantively shows the InformationNeed cannot be answered by further research "
            "(rare); never together with missing_aspects for the same insufficiency.",
            "- confidence: numeric value in [0, 1].",
            (
                "- reason: concise non-empty explanation; it MUST be at most "
                f"{DEFAULT_RAW_SEMANTIC_MAX_REASON_CHARS} characters."
            ),
            "",
            "Exclusivity:",
            "- An aspect identifier MUST NOT appear in both supported_aspects and missing_aspects.",
            "",
            "Legacy InformationNeed (evidence_expectation absent):",
            f"- The only valid aspect identifier is {LEGACY_NEED_ASPECT_ID!r}.",
            f"- Classify it as supported OR missing, never both.",
            "- Do not invent additional aspect identifiers.",
            "",
            "EvidenceExpectation present:",
            "- Use ONLY the exact canonical IDs from EvidenceExpectation.required_aspects.",
            "- Do not rename, paraphrase, or invent aspect identifiers.",
            "",
            "Forbidden output fields (deterministic policy/readiness — never emit):",
            forbidden + ".",
            "",
            "Input context:",
            "- deterministic_gap_types and other deterministic_facts are INPUT CONTEXT ONLY.",
            "- Do not copy them into output.",
        ],
    )


def render_raw_semantic_decision_output_contract() -> str:
    """Full authoritative output contract for first-pass semantic prompts."""
    return "\n".join(
        [
            raw_semantic_decision_output_instructions(),
            "",
            "REQUIRED JSON SCHEMA:",
            raw_semantic_decision_payload_schema_text(),
        ],
    )


def render_raw_semantic_decision_correction(*, rejection_code: str | None) -> str:
    """Return field-specific corrective guidance for a bounded contract rejection."""
    if rejection_code == "reason_too_long":
        return (
            "Validation failed for field 'reason': the value is too long. "
            f"The maximum allowed length is {DEFAULT_RAW_SEMANTIC_MAX_REASON_CHARS} "
            "characters. Return a corrected JSON response whose reason is non-empty "
            "and fits within this maximum."
        )
    return "Regenerate valid JSON only. Keep output compact."


def evaluate_raw_semantic_decision_payload(payload: Mapping[str, Any]) -> str | None:
    """Return a bounded rejection code, or None when the payload satisfies the contract."""
    for field in sorted(FORBIDDEN_RAW_SEMANTIC_POLICY_FIELDS):
        if field in payload:
            return f"forbidden_field:{field}"

    supported_aspects = _required_list_field(payload, "supported_aspects")
    if isinstance(supported_aspects, str):
        return supported_aspects
    if len(supported_aspects) > DEFAULT_RAW_SEMANTIC_MAX_ASPECTS:
        return "array_too_long:supported_aspects"
    aspect_code = _aspect_list_rejection(supported_aspects)
    if aspect_code is not None:
        return aspect_code

    missing_aspects = _required_list_field(payload, "missing_aspects")
    if isinstance(missing_aspects, str):
        return missing_aspects
    if len(missing_aspects) > DEFAULT_RAW_SEMANTIC_MAX_ASPECTS:
        return "array_too_long:missing_aspects"
    aspect_code = _aspect_list_rejection(missing_aspects)
    if aspect_code is not None:
        return aspect_code

    semantic_conflicts = _required_list_field(payload, "semantic_conflicts")
    if isinstance(semantic_conflicts, str):
        return semantic_conflicts
    if len(semantic_conflicts) > DEFAULT_RAW_SEMANTIC_MAX_CONFLICTS:
        return "array_too_long:semantic_conflicts"
    aspect_code = _aspect_list_rejection(semantic_conflicts)
    if aspect_code is not None:
        return aspect_code

    if "confidence" not in payload:
        return "missing_field:confidence"
    confidence = payload.get("confidence")
    if not isinstance(confidence, (int, float)):
        return "wrong_type:confidence"
    if float(confidence) < 0.0 or float(confidence) > 1.0:
        return "invalid_confidence_range"

    if "reason" not in payload:
        return "missing_field:reason"
    reason = payload.get("reason")
    if not isinstance(reason, str):
        return "wrong_type:reason"
    if not reason.strip():
        return "blank_reason"
    if len(reason) > DEFAULT_RAW_SEMANTIC_MAX_REASON_CHARS:
        return "reason_too_long"

    overlap = {
        str(item).strip()
        for item in supported_aspects
        if str(item).strip()
    } & {
        str(item).strip()
        for item in missing_aspects
        if str(item).strip()
    }
    if overlap:
        return "supported_missing_overlap"

    if (
        UNRESOLVABLE_CONFLICT_ID in semantic_conflicts
        and missing_aspects
    ):
        return "misclassified_unresolvable"

    return None


def evaluate_aspect_id_membership(
    payload: Mapping[str, Any],
    *,
    allowed_aspect_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """Return unknown aspect identifiers outside the allowed set."""
    if not allowed_aspect_ids:
        return ()
    allowed = set(allowed_aspect_ids)
    observed: list[str] = []
    for field_name in ("supported_aspects", "missing_aspects"):
        values = payload.get(field_name)
        if not isinstance(values, list):
            continue
        for item in values:
            text = str(item).strip()
            if text and text not in allowed:
                observed.append(text)
    return _dedupe_preserve_order(observed)


def render_allowed_aspect_contract(*, allowed_aspect_ids: tuple[str, ...]) -> str:
    """Call-scoped allowed-aspect instructions for first-pass and correction prompts."""
    allowed_list = ", ".join(repr(aspect_id) for aspect_id in allowed_aspect_ids)
    lines = [
        "ALLOWED ASPECT IDENTIFIERS (INPUT CONTEXT ONLY — do not copy into output):",
        f"- allowed_aspect_ids = [{allowed_list}]",
        "- supported_aspects and missing_aspects may contain ONLY values from allowed_aspect_ids.",
        "- Never invent aspect names or return descriptive labels.",
        "- Never decompose an InformationNeed into new aspect identifiers.",
        "- Labels and descriptions in information_need or evidence are semantic context only.",
        "- Classify each required aspect using canonical IDs from allowed_aspect_ids only.",
    ]
    if allowed_aspect_ids == (LEGACY_NEED_ASPECT_ID,):
        lines.extend(
            [
                "",
                "Legacy mode:",
                f"- The only valid aspect identifier is {LEGACY_NEED_ASPECT_ID!r}.",
                f"- Return {LEGACY_NEED_ASPECT_ID!r} in supported_aspects OR missing_aspects, never both.",
                "- Do not replace it with semantic labels such as payment terms, certifications, "
                "lead times, or vendor onboarding requirements.",
            ],
        )
    return "\n".join(lines)


def raw_semantic_decision_payload_contract(payload: Mapping[str, Any]) -> bool:
    return evaluate_raw_semantic_decision_payload(payload) is None


def raw_semantic_decision_from_payload(payload: Mapping[str, Any]) -> RawSemanticDecision:
    return RawSemanticDecision.from_dict(dict(payload))


@dataclass
class RawSemanticDecisionContractGate:
    """Tracks bounded contract rejection while validating call-scoped candidates."""

    allowed_aspect_ids: tuple[str, ...] = ()
    last_rejection_code: str | None = None
    last_unknown_aspect_ids: tuple[str, ...] = ()
    last_returned_supported_aspects: tuple[str, ...] = ()
    last_returned_missing_aspects: tuple[str, ...] = ()

    def accepts(self, payload: Mapping[str, Any]) -> bool:
        self.last_returned_supported_aspects = _normalized_aspect_tuple(
            payload.get("supported_aspects"),
        )
        self.last_returned_missing_aspects = _normalized_aspect_tuple(
            payload.get("missing_aspects"),
        )
        shape_rejection = evaluate_raw_semantic_decision_payload(payload)
        if shape_rejection is not None:
            self.last_rejection_code = shape_rejection
            self.last_unknown_aspect_ids = ()
            return False
        unknown = evaluate_aspect_id_membership(
            payload,
            allowed_aspect_ids=self.allowed_aspect_ids,
        )
        if unknown:
            self.last_rejection_code = "unknown_aspect_id"
            self.last_unknown_aspect_ids = unknown
            return False
        self.last_rejection_code = None
        self.last_unknown_aspect_ids = ()
        return True


def _normalized_aspect_tuple(values: Any) -> tuple[str, ...]:
    if not isinstance(values, list):
        return ()
    return tuple(str(item).strip() for item in values if str(item).strip())


def _dedupe_preserve_order(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return tuple(normalized)


def _required_list_field(payload: Mapping[str, Any], field_name: str) -> list[Any] | str:
    if field_name not in payload:
        return f"missing_field:{field_name}"
    value = payload.get(field_name)
    if not isinstance(value, list):
        return f"wrong_type:{field_name}"
    return value


def _aspect_list_rejection(values: list[Any]) -> str | None:
    if not _valid_aspect_list(values):
        return "invalid_aspect_entry"
    return None


def _valid_aspect_list(values: list[Any]) -> bool:
    return all(
        isinstance(item, str)
        and 0 < len(item.strip()) <= DEFAULT_RAW_SEMANTIC_MAX_STRING_CHARS
        for item in values
    )

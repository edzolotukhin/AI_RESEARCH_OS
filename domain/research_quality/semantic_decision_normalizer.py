from __future__ import annotations

from dataclasses import dataclass

from domain.common.exceptions import ValidationError
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.research_quality.raw_semantic_decision import RawSemanticDecision

UNRESOLVABLE_CONFLICT_ID = "unresolvable"
LEGACY_NEED_ASPECT_ID = "__legacy_need__"


@dataclass(frozen=True)
class NormalizedSemanticDecision:
    """Deterministically normalized semantic facts ready for policy evaluation."""

    supported_aspects: tuple[str, ...]
    missing_aspects: tuple[str, ...]
    semantic_conflicts: tuple[str, ...]
    confidence: float
    reason: str
    required_aspects: tuple[str, ...] = ()


def legacy_required_aspects() -> tuple[str, ...]:
    """Runtime-only canonical target for legacy InformationNeed objects."""
    return (LEGACY_NEED_ASPECT_ID,)


def normalize_semantic_decision(
    *,
    raw: RawSemanticDecision,
    evidence_expectation: EvidenceExpectation | None,
) -> NormalizedSemanticDecision:
    required = (
        evidence_expectation.required_aspects
        if evidence_expectation is not None
        else legacy_required_aspects()
    )
    supported_set = set(raw.supported_aspects)
    missing_set = set(raw.missing_aspects)
    overlap = supported_set & missing_set
    if overlap:
        raise ValidationError(
            "Semantic decision cannot list the same aspect as both supported and "
            f"missing: {', '.join(sorted(overlap))}",
        )

    required_set = set(required)
    unknown = (supported_set | missing_set) - required_set
    if unknown:
        raise ValidationError(
            "Semantic decision contains unknown aspect identifiers: "
            + ", ".join(sorted(unknown)),
        )

    supported = tuple(
        aspect for aspect in raw.supported_aspects if aspect in required_set
    )
    missing_from_raw = tuple(
        aspect for aspect in raw.missing_aspects if aspect in required_set
    )
    accounted = set(supported) | set(missing_from_raw)
    implicit_missing = tuple(
        aspect for aspect in required if aspect not in accounted
    )
    missing = _dedupe_preserve_order(missing_from_raw + implicit_missing)

    return NormalizedSemanticDecision(
        supported_aspects=supported,
        missing_aspects=missing,
        semantic_conflicts=raw.semantic_conflicts,
        confidence=raw.confidence,
        reason=raw.reason,
        required_aspects=required,
    )


def derive_semantic_coverage(
    *,
    required_aspects: tuple[str, ...],
    supported_aspects: tuple[str, ...],
    missing_aspects: tuple[str, ...],
) -> float:
    if required_aspects:
        supported_required = sum(
            1 for aspect in required_aspects if aspect in set(supported_aspects)
        )
        return supported_required / len(required_aspects)

    total = len(supported_aspects) + len(missing_aspects)
    if total == 0:
        return 0.0
    return len(supported_aspects) / total


def _dedupe_preserve_order(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return tuple(normalized)

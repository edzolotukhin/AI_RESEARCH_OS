from __future__ import annotations

from dataclasses import dataclass

from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.research_design import InformationNeed
from domain.research_quality.deterministic_sufficiency_signals import (
    DeterministicSufficiencySignals,
)
from domain.research_quality.gap_type import GapType
from domain.research_quality.policy_sufficiency_status import (
    derive_policy_sufficiency_status,
)
from domain.research_quality.raw_semantic_decision import RawSemanticDecision
from domain.research_quality.semantic_decision_normalizer import (
    UNRESOLVABLE_CONFLICT_ID,
    derive_semantic_coverage,
    normalize_semantic_decision,
)
from domain.research_quality.sufficiency_status import SufficiencyStatus


@dataclass(frozen=True)
class SufficiencyPolicyDecision:
    """Pure deterministic policy output without remediation compatibility fields."""

    status: SufficiencyStatus
    coverage: float
    gap_types: tuple[GapType, ...]
    missing_aspects: tuple[str, ...]
    confidence: float
    reason: str


def apply_sufficiency_policy(
    *,
    information_need: InformationNeed,
    evidence_expectation: EvidenceExpectation | None,
    signals: DeterministicSufficiencySignals,
    raw_semantic: RawSemanticDecision,
) -> SufficiencyPolicyDecision:
    """
    Deterministic policy boundary: semantic facts + signals → policy decision.

    Final SufficiencyStatus is derived here; the LLM must not choose it.
    Remediation/search compatibility is handled outside this function.
    """
    expectation = evidence_expectation or information_need.evidence_expectation
    normalized = normalize_semantic_decision(
        raw=raw_semantic,
        evidence_expectation=expectation,
    )
    coverage = derive_semantic_coverage(
        required_aspects=normalized.required_aspects,
        supported_aspects=normalized.supported_aspects,
        missing_aspects=normalized.missing_aspects,
    )
    gap_types = _derive_policy_gap_types(
        signals=signals,
        normalized=normalized,
        raw_semantic=raw_semantic,
        evidence_expectation=expectation,
        coverage=coverage,
    )
    status = derive_policy_sufficiency_status(
        coverage=coverage,
        gap_types=gap_types,
        evidence_count=signals.evidence_count,
    )
    return SufficiencyPolicyDecision(
        status=status,
        coverage=coverage,
        gap_types=gap_types,
        missing_aspects=normalized.missing_aspects,
        confidence=normalized.confidence,
        reason=normalized.reason,
    )


def build_policy_aspect_counts(
    *,
    evidence_expectation: EvidenceExpectation | None,
    normalized_supported: tuple[str, ...],
    normalized_missing: tuple[str, ...],
) -> tuple[int, int, int]:
    if evidence_expectation is None:
        from domain.research_quality.semantic_decision_normalizer import (
            legacy_required_aspects,
        )

        required = legacy_required_aspects()
    else:
        required = evidence_expectation.required_aspects
    supported_required = sum(
        1 for aspect in required if aspect in set(normalized_supported)
    )
    missing_required = sum(
        1 for aspect in required if aspect in set(normalized_missing)
    )
    return (len(required), supported_required, missing_required)


def _derive_policy_gap_types(
    *,
    signals: DeterministicSufficiencySignals,
    normalized,
    raw_semantic: RawSemanticDecision,
    evidence_expectation: EvidenceExpectation | None,
    coverage: float,
) -> tuple[GapType, ...]:
    gaps: list[GapType] = []
    seen: set[GapType] = set()

    def add(gap_type: GapType) -> None:
        if gap_type == GapType.NO_EVIDENCE:
            return
        if gap_type not in seen:
            seen.add(gap_type)
            gaps.append(gap_type)

    for gap_type in signals.deterministic_gap_types:
        add(gap_type)

    if normalized.semantic_conflicts:
        effective_conflicts = normalized.semantic_conflicts
        if (
            UNRESOLVABLE_CONFLICT_ID in effective_conflicts
            and raw_semantic.missing_aspects
        ):
            effective_conflicts = tuple(
                conflict
                for conflict in effective_conflicts
                if conflict != UNRESOLVABLE_CONFLICT_ID
            )
        if effective_conflicts:
            if UNRESOLVABLE_CONFLICT_ID in effective_conflicts:
                add(GapType.UNRESOLVABLE)
            else:
                add(GapType.CONFLICTING_EVIDENCE)

    if evidence_expectation is not None:
        if evidence_expectation.requires_quantitative_evidence:
            if signals.quantitative_evidence_present is False:
                add(GapType.MISSING_QUANTITATIVE_DATA)
        minimum_sources = evidence_expectation.minimum_independent_sources
        if (
            minimum_sources is not None
            and signals.independent_source_count < minimum_sources
        ):
            add(GapType.INSUFFICIENT_DIVERSITY)

    if coverage < 1.0 and normalized.missing_aspects:
        add(GapType.INSUFFICIENT_DEPTH)

    if (
        signals.evidence_count > 0
        and coverage == 0.0
        and not normalized.semantic_conflicts
    ):
        add(GapType.INSUFFICIENT_DEPTH)

    return tuple(sorted(gaps, key=lambda item: item.value))

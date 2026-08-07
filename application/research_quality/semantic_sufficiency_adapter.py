from __future__ import annotations

from domain.common.exceptions import ValidationError
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.research_design import InformationNeed
from domain.research_quality.deterministic_sufficiency_signals import (
    DeterministicSufficiencySignals,
)
from domain.research_quality.raw_semantic_decision import RawSemanticDecision
from domain.research_quality.semantic_sufficiency_assessment import (
    SemanticSufficiencyAssessment,
)
from domain.research_quality.sufficiency_policy import apply_sufficiency_policy
from domain.research_quality.sufficiency_status import SufficiencyStatus

from application.research_quality.exceptions import SemanticSufficiencyAssessmentError


def semantic_assessment_from_raw_decision(
    *,
    information_need: InformationNeed,
    signals: DeterministicSufficiencySignals,
    raw_semantic: RawSemanticDecision,
    evidence_expectation: EvidenceExpectation | None = None,
) -> SemanticSufficiencyAssessment:
    """Adapter from RawSemanticDecision to production-compatible assessment."""
    try:
        decision = apply_sufficiency_policy(
            information_need=information_need,
            evidence_expectation=evidence_expectation,
            signals=signals,
            raw_semantic=raw_semantic,
        )
    except ValidationError as exc:
        raise SemanticSufficiencyAssessmentError(str(exc), cause=exc) from exc

    return SemanticSufficiencyAssessment(
        status=decision.status,
        missing_aspects=decision.missing_aspects,
        gap_types=decision.gap_types,
        search_directives=derive_legacy_search_directives(
            status=decision.status,
            missing_aspects=decision.missing_aspects,
        ),
        confidence=decision.confidence,
        reason=decision.reason,
    )


def derive_legacy_search_directives(
    *,
    status: SufficiencyStatus,
    missing_aspects: tuple[str, ...],
) -> tuple[str, ...]:
    """
    Temporary compatibility mapping for the existing targeted research loop.

    Remediation/search planning remains outside domain policy.
    """
    if status in {SufficiencyStatus.SUFFICIENT, SufficiencyStatus.BLOCKED}:
        return ()
    return tuple(sorted(missing_aspects))

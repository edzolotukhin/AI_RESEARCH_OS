from __future__ import annotations

from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.research_design import InformationNeed
from domain.research_quality.semantic_decision_normalizer import legacy_required_aspects


def resolve_allowed_aspect_ids(
    information_need: InformationNeed,
    *,
    evidence_expectation: EvidenceExpectation | None = None,
) -> tuple[str, ...]:
    """
    Call-scoped canonical aspect identifiers for semantic sufficiency.

    Legacy mode returns the synthetic legacy target. Expectation-backed mode
    returns canonical IDs from EvidenceExpectation.required_aspects.
    """
    expectation = evidence_expectation or information_need.evidence_expectation
    if expectation is not None:
        return expectation.required_aspects
    return legacy_required_aspects()

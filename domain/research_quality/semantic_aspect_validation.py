from __future__ import annotations

from domain.planning.evidence_expectation import EvidenceExpectation
from domain.research_quality.raw_semantic_decision import RawSemanticDecision


def aspect_sets_for_policy(
    expectation: EvidenceExpectation,
    decision: RawSemanticDecision,
) -> tuple[set[str], set[str], set[str]]:
    """
    Future cross-contract helper (not production-wired in M1/M2).

    Returns (required, supported, missing) aspect identifier sets suitable
    for deterministic policy comparison.
    """
    return (
        set(expectation.required_aspects),
        set(decision.supported_aspects),
        set(decision.missing_aspects),
    )

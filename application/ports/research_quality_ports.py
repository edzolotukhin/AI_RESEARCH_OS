from __future__ import annotations

from typing import Protocol, Sequence

from domain.evidence.evidence import Evidence
from domain.planning.research_design import ResearchDesign
from domain.research_quality.research_readiness_result import ResearchReadinessResult


class ResearchSufficiencyEvaluator(Protocol):
    """Evaluates run-scoped research sufficiency against a design and evidence."""

    def evaluate(
        self,
        *,
        design: ResearchDesign,
        evidence: Sequence[Evidence],
    ) -> ResearchReadinessResult:
        ...

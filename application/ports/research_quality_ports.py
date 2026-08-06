from __future__ import annotations

from typing import Protocol, Sequence

from domain.evidence.evidence import Evidence
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.research_quality.deterministic_sufficiency_signals import (
    DeterministicSufficiencySignals,
)
from domain.research_quality.research_readiness_result import ResearchReadinessResult
from domain.research_quality.semantic_sufficiency_assessment import (
    SemanticSufficiencyAssessment,
)


class SemanticSufficiencyAssessor(Protocol):
    """Semantic sufficiency judgment scoped to one existing InformationNeed."""

    def assess(
        self,
        *,
        research_question: ResearchQuestion,
        information_need: InformationNeed,
        evidence: Sequence[Evidence],
        deterministic_signals: DeterministicSufficiencySignals,
    ) -> SemanticSufficiencyAssessment:
        ...


class ResearchSufficiencyEvaluator(Protocol):
    """Evaluates run-scoped research sufficiency against a design and evidence."""

    def evaluate(
        self,
        *,
        design: ResearchDesign,
        evidence: Sequence[Evidence],
    ) -> ResearchReadinessResult:
        ...

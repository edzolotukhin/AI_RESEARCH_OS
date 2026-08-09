from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchQuestionDTO:
    id: str
    question: str
    objective_refs: tuple[str, ...]
    priority: int
    rationale: str


@dataclass(frozen=True)
class EvidenceExpectationDTO:
    nature: str
    required_aspects: tuple[str, ...]
    geography: str = ""
    timeframe: str = ""
    minimum_independent_sources: int | None = None
    requires_quantitative_evidence: bool = False


@dataclass(frozen=True)
class InformationNeedDTO:
    id: str
    research_question_id: str
    description: str
    priority: int
    preferred_source_types: tuple[str, ...]
    timeframe: str
    geography: str
    evidence_expectation: EvidenceExpectationDTO


@dataclass(frozen=True)
class ResearchDesignDTO:
    research_questions: tuple[ResearchQuestionDTO, ...]
    information_needs: tuple[InformationNeedDTO, ...]
    source_strategy: tuple[str, ...]
    analysis_plan: tuple[str, ...]
    deliverable_plan: tuple[str, ...]
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    language: str

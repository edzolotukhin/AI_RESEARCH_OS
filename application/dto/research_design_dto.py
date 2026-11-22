from __future__ import annotations

from dataclasses import dataclass
from domain.planning.derivation import DerivationContract, InformationNeedKind
from domain.planning.research_design import EvidenceCoverageContract


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
    evidence_expectation: EvidenceExpectationDTO | None
    evidence_coverage: EvidenceCoverageContract | None = None
    kind: InformationNeedKind = InformationNeedKind.ACQUIRED
    depends_on_information_need_ids: tuple[str, ...] = ()
    derivation: DerivationContract | None = None
    output_format: str = ""
    # Planner output is never authoritative for this field. It remains None
    # until the authenticated owner confirmation boundary creates a revision.
    numeric_observation_required: bool | None = None


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
    research_subject_proposal: dict | None = None
    objective_reference_contract: str = "legacy_text_v1"

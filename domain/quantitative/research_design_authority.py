from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

FINGERPRINT_METHOD_VERSION = "qz-1"

class ResearchDesignLifecycle(StrEnum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"

class ResearchPriority(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

class HypothesisDirection(StrEnum):
    DIRECTIONAL = "DIRECTIONAL"
    NON_DIRECTIONAL = "NON_DIRECTIONAL"

class RequirementObligation(StrEnum):
    MANDATORY = "MANDATORY"
    OPTIONAL = "OPTIONAL"

class ObjectiveCoverageAuthority(StrEnum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"

class ObjectiveCoverageStatus(StrEnum):
    NOT_ASSESSED_NO_RESEARCH_DESIGN = "NOT_ASSESSED_NO_RESEARCH_DESIGN"

class QuantitativeStudyMode(StrEnum):
    DESIGN_LED = "DESIGN_LED"
    DATASET_ONLY_EXPLORATORY = "DATASET_ONLY_EXPLORATORY"

class ResearchDesignApprovalDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

@dataclass(frozen=True)
class ResearchObjective:
    objective_id: str
    statement: str
    priority: ResearchPriority

@dataclass(frozen=True)
class QuantitativeResearchQuestion:
    question_id: str
    statement: str
    objective_ids: tuple[str, ...]
    analytical_intent: str
    priority: ResearchPriority

@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: str
    statement: str
    objective_ids: tuple[str, ...]
    research_question_ids: tuple[str, ...]
    direction: HypothesisDirection
    validation_intent: str

@dataclass(frozen=True)
class AnalyticalRequirement:
    requirement_id: str
    requirement_type: str
    statement: str
    objective_ids: tuple[str, ...]
    research_question_ids: tuple[str, ...]
    obligation: RequirementObligation

@dataclass(frozen=True)
class DeliverableRequirement:
    requirement_id: str
    deliverable_type: str
    audience: str
    language: str
    obligation: RequirementObligation

@dataclass(frozen=True)
class TargetPopulation:
    geography: tuple[str, ...]
    eligibility: tuple[str, ...]
    exclusions: tuple[str, ...]
    population_constraints: tuple[str, ...] = ()

@dataclass(frozen=True)
class MethodologyIntent:
    methodology: str
    collection_mode: str
    sample_intent: str
    weighting_intent: str
    confidence_significance_expectation: str | None = None

@dataclass(frozen=True)
class QuantitativeStudyBriefVersion:
    brief_id: str
    version_id: str
    version_sequence: int
    project_id: str
    methodology: str
    title: str
    business_context: str
    business_problem: str
    decision_context: str
    research_purpose: str
    intended_audience: tuple[str, ...]
    target_deliverables: tuple[str, ...]
    constraints: tuple[str, ...]
    provenance: str
    parent_version_id: str | None
    created_at: str
    created_by: str
    lifecycle_status: ResearchDesignLifecycle
    fingerprint: str
    fingerprint_method_version: str = FINGERPRINT_METHOD_VERSION

@dataclass(frozen=True)
class QuantitativeResearchDesignVersion:
    design_id: str
    version_id: str
    version_sequence: int
    project_id: str
    methodology: str
    source_brief_version_id: str
    source_brief_fingerprint: str
    objectives: tuple[ResearchObjective, ...]
    research_questions: tuple[QuantitativeResearchQuestion, ...]
    hypotheses: tuple[Hypothesis, ...]
    target_population: TargetPopulation
    methodology_intent: MethodologyIntent
    analytical_requirements: tuple[AnalyticalRequirement, ...]
    deliverable_requirements: tuple[DeliverableRequirement, ...]
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    parent_version_id: str | None
    created_at: str
    created_by: str
    lifecycle_status: ResearchDesignLifecycle
    approval_reference: str | None
    fingerprint: str
    fingerprint_method_version: str = FINGERPRINT_METHOD_VERSION

@dataclass(frozen=True)
class QuantitativeResearchDesignApproval:
    approval_id: str
    project_id: str
    methodology: str
    design_version_id: str
    design_fingerprint: str
    actor_id: str
    decided_at: str
    decision: ResearchDesignApprovalDecision
    rationale: str
    fingerprint: str

@dataclass(frozen=True)
class QuantitativeTraceabilityManifest:
    manifest_id: str
    project_id: str
    design_version_id: str
    design_fingerprint: str
    objective_ids: tuple[str, ...]
    question_to_objectives: tuple[tuple[str, tuple[str, ...]], ...]
    requirement_to_objectives: tuple[tuple[str, tuple[str, ...]], ...]
    requirement_to_questions: tuple[tuple[str, tuple[str, ...]], ...]
    fingerprint: str
    fingerprint_method_version: str = FINGERPRINT_METHOD_VERSION

@dataclass(frozen=True)
class DatasetOnlyResearchAuthority:
    authority_id: str
    project_id: str
    run_id: str
    mode: QuantitativeStudyMode
    objective_coverage_authority: ObjectiveCoverageAuthority
    objective_coverage_status: ObjectiveCoverageStatus
    limitation: str
    fingerprint: str

@dataclass(frozen=True)
class ApprovedResearchDesignProjection:
    design_id: str
    version_id: str
    fingerprint: str
    objectives: tuple[tuple[str, str], ...]
    research_questions: tuple[tuple[str, str], ...]
    analytical_requirements: tuple[tuple[str, str, str], ...]
    target_population_summary: tuple[str, ...]
    deliverable_requirements: tuple[tuple[str, str, str], ...]
    limitations: tuple[str, ...]

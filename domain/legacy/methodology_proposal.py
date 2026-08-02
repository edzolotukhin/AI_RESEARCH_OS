"""
Legacy qualitative/quantitative methodology proposal (pre-DR-02).

Not the desk-research semantic ResearchDesign in domain.planning.research_design.
Removal condition: drop projects.research_design JSONB column and ResearchDesigner
agent when Client Manager / fieldwork vertical is retired or migrated.
"""

from dataclasses import dataclass, field


@dataclass
class BusinessProblem:
    description: str = ""
    business_decision: str = ""


@dataclass
class ResearchObjectives:
    primary: str = ""
    secondary: list[str] = field(default_factory=list)


@dataclass
class ResearchStrategy:
    recommendation: str = ""
    rationale: str = ""
    alternatives: list[str] = field(default_factory=list)


@dataclass
class Methodology:
    methods: list[str] = field(default_factory=list)
    target_audience: str = ""
    geography: str = ""
    timeline: str = ""


@dataclass
class SamplingPlan:
    sample_size: int | None = None
    sampling_method: str = ""
    quotas: list[str] = field(default_factory=list)


@dataclass
class Risk:
    description: str = ""
    mitigation: str = ""


@dataclass
class RiskAssessment:
    risks: list[Risk] = field(default_factory=list)


@dataclass
class MethodologyProposal:
    """
    Deprecated project-level methodology proposal aggregate.

    Persisted in PostgreSQL projects.research_design JSONB for backward
    compatibility only. No production desk-research path writes this field.
    """

    business_problem: BusinessProblem = field(default_factory=BusinessProblem)
    objectives: ResearchObjectives = field(default_factory=ResearchObjectives)
    strategy: ResearchStrategy = field(default_factory=ResearchStrategy)
    methodology: Methodology = field(default_factory=Methodology)
    sampling: SamplingPlan = field(default_factory=SamplingPlan)
    risks: RiskAssessment = field(default_factory=RiskAssessment)

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.findings.insight import Insight
from domain.research_brief import ResearchBrief
from domain.planning.research_design import ResearchDesign


@dataclass(frozen=True)
class FindingCandidate:
    """Structured analysis output before authoritative provenance is attached."""

    statement: str
    rationale: str
    evidence_refs: tuple[str, ...]
    research_question_refs: tuple[str, ...] = ()
    information_need_refs: tuple[str, ...] = ()
    finding_type: str = "synthesis"
    confidence: float | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class InsightCandidate:
    """Structured insight output before authoritative provenance is attached."""

    statement: str
    implication: str
    finding_refs: tuple[str, ...]
    research_question_refs: tuple[str, ...] = ()
    confidence: float | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class AnalysisInput:
    """Run-scoped bounded input for the analysis engine."""

    project_id: str
    workflow_run_id: str
    research_design_id: str
    brief: ResearchBrief
    design: ResearchDesign
    evidence_batch: tuple[Evidence, ...]
    batch_question_id: str | None = None
    persisted_findings: tuple[Finding, ...] = ()


class AnalysisEngine(Protocol):
    method_name: str

    def analyze_findings(self, analysis_input: AnalysisInput) -> list[FindingCandidate]:
        ...

    def analyze_insights(self, analysis_input: AnalysisInput) -> list[InsightCandidate]:
        ...


class FindingRepository(Protocol):
    def create(self, finding: Finding) -> int:
        ...

    def get_by_id(self, finding_id: str) -> Finding | None:
        ...

    def get_by_deduplication_key(
        self,
        workflow_run_id: str,
        deduplication_key: str,
    ) -> Finding | None:
        ...

    def list_for_project(
        self,
        project_id: str,
        *,
        workflow_run_id: str | None = None,
        research_question_id: str | None = None,
        information_need_id: str | None = None,
        evidence_id: str | None = None,
    ) -> list[Finding]:
        ...


class InsightRepository(Protocol):
    def create(self, insight: Insight) -> int:
        ...

    def get_by_id(self, insight_id: str) -> Insight | None:
        ...

    def get_by_deduplication_key(
        self,
        workflow_run_id: str,
        deduplication_key: str,
    ) -> Insight | None:
        ...

    def list_for_project(
        self,
        project_id: str,
        *,
        workflow_run_id: str | None = None,
        research_question_id: str | None = None,
        finding_id: str | None = None,
    ) -> list[Insight]:
        ...

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.findings.insight import Insight
from domain.planning.research_design import ResearchDesign
from domain.reports.report import Report
from domain.research_brief import ResearchBrief
from domain.sources.source import Source


@dataclass(frozen=True)
class ReportSectionCandidate:
    title: str
    content: str
    research_question_refs: tuple[str, ...] = ()
    finding_refs: tuple[str, ...] = ()
    insight_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReportCandidate:
    title: str
    executive_summary: str
    sections: tuple[ReportSectionCandidate, ...]
    limitations: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReportInput:
    project_id: str
    workflow_run_id: str
    research_design_id: str
    brief: ResearchBrief
    design: ResearchDesign
    findings: tuple[Finding, ...]
    insights: tuple[Insight, ...]
    evidence_by_id: dict[str, Evidence]
    sources_by_id: dict[str, Source]
    section_titles: tuple[str, ...]
    batch_question_id: str | None = None
    section_summaries: tuple[str, ...] = ()


class ReportEngine(Protocol):
    method_name: str

    def generate_sections(
        self,
        report_input: ReportInput,
    ) -> tuple[ReportSectionCandidate, ...]:
        ...

    def generate_executive_summary(
        self,
        report_input: ReportInput,
        *,
        sections: tuple[ReportSectionCandidate, ...],
    ) -> ReportCandidate:
        ...


class ReportRepository(Protocol):
    def create(self, report: Report) -> int:
        ...

    def get_by_id(self, report_id: str) -> Report | None:
        ...

    def get_by_deduplication_key(
        self,
        workflow_run_id: str,
        deduplication_key: str,
    ) -> Report | None:
        ...

    def list_for_project(
        self,
        project_id: str,
        *,
        workflow_run_id: str | None = None,
    ) -> list[Report]:
        ...

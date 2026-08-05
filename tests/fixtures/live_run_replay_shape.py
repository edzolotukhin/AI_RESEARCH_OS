"""Offline replay fixture — live-shaped desk research run (no secrets)."""

from __future__ import annotations

from uuid import uuid4

from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType
from domain.findings.insight import Insight
from domain.planning.research_design import ResearchDesign, ResearchQuestion
from domain.reports.report import Report
from domain.reports.report_section import ReportSection

LIVE_RUN_ID = "ed6d88a8-dd0e-4aad-b035-31b31bbe433e"
PROJECT_ID = "project-live-replay"
DESIGN_ID = "design-live-replay"


def live_research_design() -> ResearchDesign:
    questions = tuple(
        ResearchQuestion(
            id=f"RQ{index}",
            question=f"Research question {index} about market entry and logistics",
            objective_refs=(f"objective-{index}", "market", "entry"),
            priority=index,
            rationale=f"Rationale for RQ{index}",
        )
        for index in range(1, 7)
    )
    return ResearchDesign(
        id=DESIGN_ID,
        research_questions=questions,
        information_needs=(),
        source_strategy=("web",),
        analysis_plan=("synthesize",),
        deliverable_plan=tuple(f"Section {index}" for index in range(1, 7)),
        assumptions=(),
        limitations=("Desk research only", "Secondary sources"),
        language="en",
    )


def live_findings(*, count: int = 52) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    for index in range(count):
        rq = f"RQ{(index % 6) + 1}"
        finding_type = FindingType.SYNTHESIS
        if index == 10:
            finding_type = FindingType.CONTRADICTION
            statement = "Sources disagree on OTIF performance benchmarks across regions"
        else:
            statement = f"Finding {index} for {rq} with market evidence"
        findings.append(
            Finding(
                id=f"finding-{index:03d}",
                project_id=PROJECT_ID,
                workflow_run_id=LIVE_RUN_ID,
                research_design_id=DESIGN_ID,
                statement=statement,
                rationale="Derived from evidence",
                evidence_refs=(f"evidence-{index:03d}",),
                created_at="2026-07-29T00:00:00+00:00",
                research_question_refs=(rq,),
                finding_type=finding_type,
                deduplication_key=f"dedup-finding-{index:03d}",
                confidence=0.8 if index % 5 else 0.4,
            ),
        )
    return tuple(findings)


def live_insights(*, count: int = 10) -> tuple[Insight, ...]:
    return tuple(
        Insight(
            id=f"insight-{index:03d}",
            project_id=PROJECT_ID,
            workflow_run_id=LIVE_RUN_ID,
            research_design_id=DESIGN_ID,
            statement=f"Insight {index} implication",
            implication="Strategic implication",
            finding_refs=(f"finding-{index:03d}",),
            research_question_refs=(),
            confidence=0.75,
            created_at="2026-07-29T00:00:00+00:00",
            deduplication_key=f"dedup-insight-{index:03d}",
        )
        for index in range(count)
    )


def live_raw_sections(*, count: int = 57) -> tuple[ReportSection, ...]:
    """Simulate pre-remediation section explosion."""
    sections: list[ReportSection] = []
    for index in range(count):
        rq = f"RQ{(index % 6) + 1}"
        content = f"Analysis for section {index} addressing {rq} objectives market entry"
        if index == 5:
            content += " OTIF >=95% lead time <=10%"
        sections.append(
            ReportSection(
                id=str(uuid4()),
                title=f"Section {index}",
                content=content,
                research_question_refs=(rq, f"RQ{(index % 6) + 2}"),
                finding_refs=(f"finding-{index:03d}",),
                insight_refs=(),
                evidence_refs=(f"evidence-{index:03d}",),
                citation_ids=("S1",),
                metadata={"batch_question_id": rq, "primary_research_question_id": rq},
            ),
        )
    return tuple(sections)


def live_citation_registry() -> dict:
    return {
        "S1": {
            "citation_id": "S1",
            "source_id": "source-001",
            "title": "Industry report",
            "canonical_url": "https://example.com/report",
            "published_at": None,
            "retrieved_at": "2026-07-29T00:00:00+00:00",
            "source_type": "web",
        },
    }


def live_report(*, sections: tuple[ReportSection, ...]) -> Report:
    return Report(
        id=str(uuid4()),
        project_id=PROJECT_ID,
        workflow_run_id=LIVE_RUN_ID,
        research_design_id=DESIGN_ID,
        title="Live Replay Report",
        language="en",
        sections=sections,
        executive_summary="Executive summary of market entry research.",
        limitations=("Desk research only", "Secondary sources"),
        created_at="2026-07-29T00:00:00+00:00",
        generation_method="llm",
        finding_refs=tuple(sorted({ref for s in sections for ref in s.finding_refs})),
        insight_refs=(),
        evidence_refs=tuple(sorted({ref for s in sections for ref in s.evidence_refs})),
        citation_registry=live_citation_registry(),
        deduplication_key="dedup-live-report",
        revision_number=1,
        approval_status="draft",
        metadata={},
    )

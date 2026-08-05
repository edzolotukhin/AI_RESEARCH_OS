from __future__ import annotations

from domain.findings.finding import Finding
from domain.findings.insight import Insight
from domain.planning.research_design import ResearchDesign
from domain.reports.report_section import ReportSection

from application.ports.report_ports import ReportSectionCandidate


def section_supports_question(
    section: ReportSection | ReportSectionCandidate,
    question_id: str,
    findings: list[Finding] | tuple[Finding, ...],
) -> bool:
    if question_id in section.research_question_refs:
        return True
    finding_ids = set(section.finding_refs)
    return any(
        question_id in finding.research_question_refs
        for finding in findings
        if finding.id in finding_ids
    )


def covered_research_question_ids(
    sections: tuple[ReportSection, ...] | list[ReportSection],
    *,
    findings: list[Finding] | tuple[Finding, ...],
    design: ResearchDesign,
) -> set[str]:
    covered: set[str] = set()
    for section in sections:
        covered.update(section.research_question_refs)
    for question in design.research_questions:
        if question.id in covered:
            continue
        if any(
            section_supports_question(section, question.id, findings)
            for section in sections
        ):
            covered.add(question.id)
    return covered


def missing_research_question_ids(
    sections: tuple[ReportSection, ...] | list[ReportSection],
    *,
    findings: list[Finding] | tuple[Finding, ...],
    design: ResearchDesign,
) -> tuple[str, ...]:
    covered = covered_research_question_ids(
        sections,
        findings=findings,
        design=design,
    )
    return tuple(
        question.id
        for question in design.research_questions
        if question.id not in covered
    )


def enrich_research_question_refs(
    candidate: ReportSectionCandidate,
    *,
    batch_question_id: str | None,
    findings_by_id: dict[str, Finding],
    insights_by_id: dict[str, Insight],
    design: ResearchDesign,
) -> tuple[str, ...]:
    allowed = {question.id for question in design.research_questions}
    refs: set[str] = {
        ref for ref in candidate.research_question_refs if ref in allowed
    }
    if batch_question_id and batch_question_id in allowed:
        refs.add(batch_question_id)
    for finding_id in candidate.finding_refs:
        finding = findings_by_id.get(finding_id)
        if finding is not None:
            refs.update(
                ref for ref in finding.research_question_refs if ref in allowed
            )
    for insight_id in candidate.insight_refs:
        insight = insights_by_id.get(insight_id)
        if insight is None:
            continue
        refs.update(
            ref for ref in insight.research_question_refs if ref in allowed
        )
    return tuple(sorted(refs))


def findings_available_for_question(
    findings: list[Finding] | tuple[Finding, ...],
    question_id: str,
) -> tuple[Finding, ...]:
    return tuple(
        item for item in findings if question_id in item.research_question_refs
    )

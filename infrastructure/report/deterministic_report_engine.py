from __future__ import annotations

from uuid import uuid4

from domain.findings.finding import Finding
from domain.findings.insight import Insight

from application.ports.report_ports import (
    ReportCandidate,
    ReportInput,
    ReportSectionCandidate,
)


class DeterministicReportEngine:
    """Explicit test/smoke report writer consuming persisted analytical records."""

    method_name = "deterministic"

    def generate_sections(
        self,
        report_input: ReportInput,
    ) -> tuple[ReportSectionCandidate, ...]:
        design = report_input.design
        question_by_id = {question.id: question for question in design.research_questions}
        sections: list[ReportSectionCandidate] = []

        if report_input.batch_question_id is not None:
            question_id = report_input.batch_question_id
            question = question_by_id.get(question_id)
            title = question.question if question is not None else question_id
            sections.append(
                self._section_for_material(
                    title=title,
                    question_id=question_id,
                    findings=report_input.findings,
                    insights=report_input.insights,
                ),
            )
            return tuple(sections)

        titles = report_input.section_titles or tuple(
            question.question for question in design.research_questions
        )
        for index, title in enumerate(titles):
            question_id = (
                design.research_questions[index].id
                if index < len(design.research_questions)
                else f"section-{index + 1}"
            )
            batch_findings = tuple(
                item
                for item in report_input.findings
                if question_id in item.research_question_refs or not item.research_question_refs
            )
            batch_insights = tuple(
                item
                for item in report_input.insights
                if question_id in item.research_question_refs or not item.research_question_refs
            )
            if not batch_findings and not batch_insights:
                continue
            sections.append(
                self._section_for_material(
                    title=title,
                    question_id=question_id,
                    findings=batch_findings,
                    insights=batch_insights,
                ),
            )
        return tuple(sections)

    def generate_executive_summary(
        self,
        report_input: ReportInput,
        *,
        sections: tuple[ReportSectionCandidate, ...],
    ) -> ReportCandidate:
        brief = report_input.brief
        insight_statements = [item.statement for item in report_input.insights]
        summary = (
            f"This report synthesizes desk research findings for '{brief.business_question}'. "
            f"It covers {len(sections)} structured sections grounded in "
            f"{len(report_input.findings)} findings and {len(report_input.insights)} insights."
        )
        if insight_statements:
            summary += f" Key insight: {insight_statements[0]}"
        limitations = tuple(report_input.design.limitations)
        return ReportCandidate(
            title=brief.title or "Desk Research Report",
            executive_summary=summary,
            sections=sections,
            limitations=limitations,
            metadata={"deterministic": "true", "language": brief.language},
        )

    def _section_for_material(
        self,
        *,
        title: str,
        question_id: str,
        findings: tuple[Finding, ...],
        insights: tuple[Insight, ...],
    ) -> ReportSectionCandidate:
        finding_refs = tuple(sorted({item.id for item in findings}))
        insight_refs = tuple(sorted({item.id for item in insights}))
        evidence_refs = tuple(
            sorted({ref for item in findings for ref in item.evidence_refs}),
        )
        finding_text = "; ".join(item.statement for item in findings[:3])
        insight_text = "; ".join(item.statement for item in insights[:2])
        content = (
            f"Analysis for {title}: {finding_text}. "
            f"Implications: {insight_text}."
        )
        return ReportSectionCandidate(
            title=title,
            content=content,
            research_question_refs=(question_id,),
            finding_refs=finding_refs,
            insight_refs=insight_refs,
            evidence_refs=evidence_refs,
            metadata={"section_id": str(uuid4())},
        )

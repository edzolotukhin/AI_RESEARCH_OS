from __future__ import annotations

from domain.reports.report import Report

from api.schemas.reports import ReportResponse, ReportSectionResponse


def report_to_response(report: Report) -> ReportResponse:
    return ReportResponse(
        id=report.id,
        project_id=report.project_id,
        workflow_run_id=report.workflow_run_id,
        research_design_id=report.research_design_id,
        title=report.title,
        language=report.language,
        sections=[
            ReportSectionResponse(
                id=section.id,
                title=section.title,
                content=section.content,
                research_question_refs=list(section.research_question_refs),
                finding_refs=list(section.finding_refs),
                insight_refs=list(section.insight_refs),
                evidence_refs=list(section.evidence_refs),
                citation_ids=list(section.citation_ids),
            )
            for section in report.sections
        ],
        executive_summary=report.executive_summary,
        limitations=list(report.limitations),
        created_at=report.created_at,
        generation_method=report.generation_method,
        finding_refs=list(report.finding_refs),
        insight_refs=list(report.insight_refs),
        evidence_refs=list(report.evidence_refs),
        citation_registry=dict(report.citation_registry),
    )

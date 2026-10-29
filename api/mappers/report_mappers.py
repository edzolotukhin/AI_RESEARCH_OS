from __future__ import annotations

from domain.reports.report import Report

from api.schemas.reports import ReportResponse, ReportSectionResponse


def report_to_response(report: Report, *, delivery=None) -> ReportResponse:
    if delivery is not None:
        document = delivery.document
        return ReportResponse(
            id=report.id, project_id=report.project_id,
            workflow_run_id=report.workflow_run_id,
            research_design_id=report.research_design_id,
            title=document.title, language=report.language,
            sections=[ReportSectionResponse(
                id=f"section-{index}", title=item.title,
                content="\n\n".join(value.text for value in item.paragraphs),
                citation_ids=list(dict.fromkeys(
                    key for value in item.paragraphs for key in value.citation_keys
                )),
            ) for index, item in enumerate(document.sections, 1)],
            executive_summary="\n\n".join(item.text for item in document.executive_summary),
            limitations=list(document.limitations), created_at=report.created_at,
            generation_method=report.generation_method,
            citation_registry={item.display_key: {
                "title": item.title, "canonical_url": item.canonical_url,
            } for item in document.references},
            report_contract_version=document.report_contract_version,
            revision_number=delivery.provenance.revision_number,
            authority_digest=delivery.provenance.authority_digest,
            presentation_digest=delivery.provenance.presentation_digest,
            references=[
                f"[{item.display_key}] {item.title}" +
                (f" — {item.canonical_url}" if item.canonical_url else "")
                for item in document.references
            ],
        )
    if report.metadata.get("report_contract_version") == "desk_editorial_v1":
        return ReportResponse(
            id=report.id, project_id=report.project_id,
            workflow_run_id=report.workflow_run_id,
            research_design_id=report.research_design_id,
            title=report.title, language=report.language, sections=[],
            executive_summary="", limitations=[], created_at=report.created_at,
            generation_method=report.generation_method,
            report_contract_version="desk_editorial_v1",
            revision_number=report.revision_number,
            delivery_available=False,
        )
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
        report_contract_version=report.metadata.get("report_contract_version"),
        revision_number=report.revision_number,
    )

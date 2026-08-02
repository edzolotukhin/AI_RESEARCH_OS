from __future__ import annotations

from datetime import datetime

from domain.reports.report import Report
from domain.reports.report_section import ReportSection

from infrastructure.persistence.postgresql.models.report_model import ReportModel


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def report_to_model(report: Report, *, version: int) -> ReportModel:
    return ReportModel(
        id=report.id,
        project_id=report.project_id,
        workflow_run_id=report.workflow_run_id,
        research_design_id=report.research_design_id,
        title=report.title,
        language=report.language,
        sections=[section.to_dict() for section in report.sections],
        executive_summary=report.executive_summary,
        limitations=list(report.limitations),
        created_at=_parse_datetime(report.created_at),
        generation_method=report.generation_method,
        finding_refs=list(report.finding_refs),
        insight_refs=list(report.insight_refs),
        evidence_refs=list(report.evidence_refs),
        citation_registry=dict(report.citation_registry),
        deduplication_key=report.deduplication_key,
        revision_number=report.revision_number,
        previous_report_id=report.previous_report_id,
        approval_status=report.approval_status,
        metadata_json=dict(report.metadata),
        version=version,
    )


def report_from_model(model: ReportModel) -> Report:
    return Report(
        id=model.id,
        project_id=model.project_id,
        workflow_run_id=model.workflow_run_id,
        research_design_id=model.research_design_id,
        title=model.title,
        language=model.language,
        sections=tuple(
            ReportSection.from_dict(item) for item in (model.sections or [])
        ),
        executive_summary=model.executive_summary,
        limitations=tuple(model.limitations or ()),
        created_at=model.created_at.isoformat(),
        generation_method=model.generation_method,
        finding_refs=tuple(model.finding_refs or ()),
        insight_refs=tuple(model.insight_refs or ()),
        evidence_refs=tuple(model.evidence_refs or ()),
        citation_registry=dict(model.citation_registry or {}),
        deduplication_key=model.deduplication_key,
        revision_number=int(getattr(model, "revision_number", 1) or 1),
        previous_report_id=getattr(model, "previous_report_id", None),
        approval_status=str(getattr(model, "approval_status", "draft") or "draft"),
        metadata=dict(model.metadata_json or {}),
        version=model.version,
    )

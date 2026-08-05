from __future__ import annotations

from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType
from domain.planning.research_design import ResearchDesign
from domain.reports.report_section import ReportSection

from application.report.report_assembly import CONTRADICTION_SECTION_TITLE


def validate_report_structure(
    *,
    sections: tuple[ReportSection, ...] | list[ReportSection],
    executive_summary: str,
    limitations: tuple[str, ...],
    design: ResearchDesign,
    findings: list[Finding] | tuple[Finding, ...] | None = None,
) -> tuple[str, ...]:
    """Deterministic pre-persist structure checks for report assembly."""
    errors: list[str] = []
    if not executive_summary.strip():
        errors.append("executive_summary_required")
    if not sections:
        errors.append("sections_required")
    for limitation in design.limitations:
        if not _limitation_reflected(limitation, limitations):
            errors.append(f"missing_design_limitation:{limitation[:80]}")
    if findings is not None:
        contradictions = [
            item for item in findings if item.finding_type == FindingType.CONTRADICTION
        ]
        if contradictions and not _contradictions_acknowledged(sections, executive_summary):
            errors.append("contradiction_acknowledgment_required")
    return tuple(errors)


def _limitation_reflected(limitation: str, report_limitations: tuple[str, ...]) -> bool:
    needle = limitation.strip().lower()
    if not needle:
        return True
    return any(
        needle in item.lower() or item.lower() in needle for item in report_limitations
    )


def _contradictions_acknowledged(
    sections: tuple[ReportSection, ...] | list[ReportSection],
    executive_summary: str,
) -> bool:
    if any(section.title == CONTRADICTION_SECTION_TITLE for section in sections):
        return True
    keywords = ("contradict", "conflict", "uncertain", "mixed", "inconsistent")
    corpus = " ".join([executive_summary, *(section.content for section in sections)]).lower()
    return any(keyword in corpus for keyword in keywords)

from __future__ import annotations

from domain.planning.research_design import ResearchDesign
from domain.reports.report_section import ReportSection


def validate_report_structure(
    *,
    sections: tuple[ReportSection, ...] | list[ReportSection],
    executive_summary: str,
    limitations: tuple[str, ...],
    design: ResearchDesign,
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
    return tuple(errors)


def _limitation_reflected(limitation: str, report_limitations: tuple[str, ...]) -> bool:
    needle = limitation.strip().lower()
    if not needle:
        return True
    return any(
        needle in item.lower() or item.lower() in needle for item in report_limitations
    )

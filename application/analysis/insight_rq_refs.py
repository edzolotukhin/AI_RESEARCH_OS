from __future__ import annotations

from domain.findings.finding import Finding
from domain.planning.research_design import ResearchDesign

from application.ports.analysis_ports import InsightCandidate


def derive_insight_research_question_refs(
    candidate: InsightCandidate,
    *,
    findings_by_id: dict[str, Finding],
    design: ResearchDesign,
) -> tuple[str, ...]:
    """Inherit RQ refs from supporting findings when insight refs are absent."""
    allowed = {question.id for question in design.research_questions}
    refs: set[str] = {
        ref for ref in candidate.research_question_refs if ref in allowed
    }
    for finding_id in candidate.finding_refs:
        finding = findings_by_id.get(finding_id)
        if finding is None:
            continue
        refs.update(
            ref for ref in finding.research_question_refs if ref in allowed
        )
    return tuple(sorted(refs))

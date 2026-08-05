from __future__ import annotations

import re
from dataclasses import dataclass

from domain.findings.finding import Finding
from domain.findings.insight import Insight
from domain.planning.research_design import ResearchDesign, ResearchQuestion
from domain.reports.report_section import ReportSection

from application.ports.report_ports import ReportSectionCandidate
from application.report.coverage_validation import section_supports_question

_WHITESPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"[a-z0-9]{4,}", re.IGNORECASE)

# v1 thresholds — bounded, explainable, testable
DEFAULT_MIN_SUBSTANTIVE_SECTIONS_PER_RQ = 1
DEFAULT_MIN_FINDING_COVERAGE_RATIO = 0.25
DEFAULT_MIN_CITATION_COVERAGE_RATIO = 0.20


@dataclass(frozen=True)
class RQCoverageMetrics:
    rq_id: str
    evidence_count: int
    finding_count: int
    insight_count: int
    referenced_finding_count: int
    section_count: int
    substantive_section_count: int
    finding_coverage_ratio: float
    citation_coverage_ratio: float

    def passes_substantive_gate(
        self,
        *,
        min_substantive_sections: int = DEFAULT_MIN_SUBSTANTIVE_SECTIONS_PER_RQ,
        min_finding_ratio: float = DEFAULT_MIN_FINDING_COVERAGE_RATIO,
    ) -> bool:
        if self.substantive_section_count < min_substantive_sections:
            return False
        if self.finding_count == 0:
            return True
        if self.referenced_finding_count >= 1:
            return True
        return self.finding_coverage_ratio >= min_finding_ratio


def _tokens(text: str) -> set[str]:
    return {match.group(0).lower() for match in _TOKEN.finditer(text)}


def objective_tokens(question: ResearchQuestion) -> set[str]:
    parts = [question.question, question.rationale or ""]
    parts.extend(question.objective_refs or ())
    return _tokens(" ".join(parts))


def primary_research_question_for_section(
    section: ReportSection | ReportSectionCandidate,
    *,
    batch_question_id: str | None = None,
) -> str | None:
    """Return the single primary RQ a section substantively addresses."""
    metadata = getattr(section, "metadata", None) or {}
    primary = metadata.get("primary_research_question_id")
    if isinstance(primary, str) and primary:
        return primary
    if batch_question_id and batch_question_id in section.research_question_refs:
        return batch_question_id
    refs = section.research_question_refs
    if len(refs) == 1:
        return refs[0]
    return None


def section_substantively_covers_question(
    section: ReportSection | ReportSectionCandidate,
    question: ResearchQuestion,
    *,
    findings: tuple[Finding, ...] | list[Finding],
    batch_question_id: str | None = None,
    min_token_overlap: int = 2,
) -> bool:
    """Substantive coverage requires primary RQ alignment, not incidental multi-tagging."""
    if not section_supports_question(section, question.id, findings):
        return False
    primary = primary_research_question_for_section(
        section,
        batch_question_id=batch_question_id,
    )
    if primary is not None and primary != question.id:
        return False
    if primary == question.id:
        return True
    # Dedicated RQ section title prefix e.g. "RQ3:" or "Ответ на RQ3"
    title_lower = section.title.lower()
    if question.id.lower() in title_lower:
        return True
    objectives = objective_tokens(question)
    if not objectives:
        return False
    content_tokens = _tokens(f"{section.title} {section.content}")
    overlap = len(objectives & content_tokens)
    return overlap >= min(min_token_overlap, len(objectives))


def compute_rq_coverage_metrics(
    *,
    question: ResearchQuestion,
    sections: tuple[ReportSection, ...] | list[ReportSection],
    findings: tuple[Finding, ...] | list[Finding],
    insights: tuple[Insight, ...] | list[Insight],
    evidence_count: int,
    section_batch_map: dict[str, str | None] | None = None,
) -> RQCoverageMetrics:
    section_batch_map = section_batch_map or {}
    rq_findings = [f for f in findings if question.id in f.research_question_refs]
    rq_insights = [i for i in insights if question.id in i.research_question_refs]
    supporting_sections = [
        s for s in sections if section_supports_question(s, question.id, findings)
    ]
    substantive_sections = [
        s
        for s in supporting_sections
        if section_substantively_covers_question(
            s,
            question,
            findings=findings,
            batch_question_id=section_batch_map.get(getattr(s, "id", "")),
        )
    ]
    referenced_findings: set[str] = set()
    cited_sections = 0
    for section in supporting_sections:
        section_findings = {
            ref for ref in section.finding_refs if ref in {f.id for f in rq_findings}
        }
        referenced_findings.update(section_findings)
        if section.citation_ids:
            cited_sections += 1
    finding_count = len(rq_findings)
    finding_ratio = (
        len(referenced_findings) / finding_count if finding_count else 1.0
    )
    section_count = len(supporting_sections)
    citation_ratio = (
        cited_sections / section_count if section_count else 0.0
    )
    return RQCoverageMetrics(
        rq_id=question.id,
        evidence_count=evidence_count,
        finding_count=finding_count,
        insight_count=len(rq_insights),
        referenced_finding_count=len(referenced_findings),
        section_count=section_count,
        substantive_section_count=len(substantive_sections),
        finding_coverage_ratio=round(finding_ratio, 4),
        citation_coverage_ratio=round(citation_ratio, 4),
    )


def missing_substantive_research_question_ids(
    sections: tuple[ReportSection, ...] | list[ReportSection],
    *,
    findings: tuple[Finding, ...] | list[Finding],
    insights: tuple[Insight, ...] | list[Insight],
    design: ResearchDesign,
    evidence_counts_by_rq: dict[str, int] | None = None,
    section_batch_map: dict[str, str | None] | None = None,
    min_substantive_sections: int = DEFAULT_MIN_SUBSTANTIVE_SECTIONS_PER_RQ,
    min_finding_ratio: float = DEFAULT_MIN_FINDING_COVERAGE_RATIO,
) -> tuple[str, ...]:
    missing: list[str] = []
    evidence_counts_by_rq = evidence_counts_by_rq or {}
    for question in design.research_questions:
        metrics = compute_rq_coverage_metrics(
            question=question,
            sections=sections,
            findings=findings,
            insights=insights,
            evidence_count=evidence_counts_by_rq.get(question.id, 0),
            section_batch_map=section_batch_map,
        )
        if not metrics.passes_substantive_gate(
            min_substantive_sections=min_substantive_sections,
            min_finding_ratio=min_finding_ratio,
        ):
            missing.append(question.id)
    return tuple(missing)


def validate_two_dimensional_coverage(
    sections: tuple[ReportSection, ...] | list[ReportSection],
    *,
    findings: tuple[Finding, ...] | list[Finding],
    insights: tuple[Insight, ...] | list[Insight],
    design: ResearchDesign,
    evidence_counts_by_rq: dict[str, int] | None = None,
    section_batch_map: dict[str, str | None] | None = None,
) -> tuple[str, ...]:
    """Return error codes if structural or substantive coverage fails."""
    from application.report.coverage_validation import missing_research_question_ids

    errors: list[str] = []
    structural_missing = missing_research_question_ids(
        sections,
        findings=findings,
        design=design,
    )
    for rq_id in structural_missing:
        errors.append(f"structural_coverage_missing:{rq_id}")
    substantive_missing = missing_substantive_research_question_ids(
        sections,
        findings=findings,
        insights=insights,
        design=design,
        evidence_counts_by_rq=evidence_counts_by_rq,
        section_batch_map=section_batch_map,
    )
    for rq_id in substantive_missing:
        errors.append(f"substantive_coverage_missing:{rq_id}")
    return tuple(errors)

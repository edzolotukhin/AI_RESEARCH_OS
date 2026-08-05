from __future__ import annotations

import re
from uuid import uuid4

from domain.findings.finding import Finding
from domain.planning.research_design import ResearchDesign
from domain.reports.report import Report
from domain.reviews.review_issue import ReviewIssue, ReviewIssueSeverity, ReviewIssueType

from application.report.report_assembly import (
    CONTRADICTION_SECTION_TITLE,
    contradiction_findings,
    detect_unsupported_numeric_claims,
)
from application.report.substantive_coverage import (
    validate_two_dimensional_coverage,
    compute_rq_coverage_metrics,
)

_ACK_KEYWORDS = ("contradict", "conflict", "uncertain", "mixed", "inconsistent")
_CITATION_MARKER = re.compile(r"\[(S\d+)\]")


def run_deterministic_pre_review(
    *,
    report: Report,
    design: ResearchDesign,
    findings: list[Finding],
    insights: list,
) -> tuple[ReviewIssue, ...]:
    """Tier-1 deterministic checks before bounded semantic LLM review."""
    issues: list[ReviewIssue] = []
    findings_by_id = {item.id: item for item in findings}
    evidence_counts: dict[str, int] = {}
    for finding in findings:
        for rq in finding.research_question_refs:
            evidence_counts[rq] = evidence_counts.get(rq, 0) + len(finding.evidence_refs)

    section_batch_map = {
        section.id: (section.metadata or {}).get("primary_research_question_id")
        for section in report.sections
    }

    coverage_errors = validate_two_dimensional_coverage(
        report.sections,
        findings=findings,
        insights=insights,
        design=design,
        evidence_counts_by_rq=evidence_counts,
        section_batch_map=section_batch_map,
    )
    for code in coverage_errors:
        issues.append(
            _issue(
                issue_type=ReviewIssueType.COVERAGE_GAP,
                severity=ReviewIssueSeverity.MAJOR,
                message=f"Deterministic coverage gate: {code}",
                research_question_refs=_rq_from_code(code),
            ),
        )

    contradictions = contradiction_findings(findings)
    if contradictions and not _contradictions_acknowledged(report):
        issues.append(
            _issue(
                issue_type=ReviewIssueType.CONTRADICTION,
                severity=ReviewIssueSeverity.MAJOR,
                message="Contradictory findings exist but are not acknowledged in the report",
                finding_refs=tuple(f.id for f in contradictions),
            ),
        )

    registry = report.citation_registry or {}
    for section in report.sections:
        kind = (section.metadata or {}).get("section_kind")
        if kind in {"limitations", "contradictions"}:
            continue
        for cid in section.citation_ids:
            if cid not in registry:
                issues.append(
                    _issue(
                        issue_type=ReviewIssueType.MISSING_CITATION,
                        severity=ReviewIssueSeverity.MAJOR,
                        message=f"Citation marker {cid} not in registry",
                        report_section_id=section.id,
                    ),
                )
        if section.finding_refs and not section.citation_ids:
            issues.append(
                _issue(
                    issue_type=ReviewIssueType.MISSING_CITATION,
                    severity=ReviewIssueSeverity.MAJOR,
                    message="Section has finding refs but no citation markers",
                    report_section_id=section.id,
                    finding_refs=section.finding_refs,
                ),
            )
        unsupported = detect_unsupported_numeric_claims(
            section.content,
            finding_refs=section.finding_refs,
            findings_by_id=findings_by_id,
        )
        for snippet in unsupported:
            issues.append(
                _issue(
                    issue_type=ReviewIssueType.UNSUPPORTED_CLAIM,
                    severity=ReviewIssueSeverity.MAJOR,
                    message=f"Unsupported numeric/prescriptive claim: {snippet}",
                    report_section_id=section.id,
                    finding_refs=section.finding_refs,
                ),
            )
        if section.finding_refs and not _CITATION_MARKER.search(section.content):
            issues.append(
                _issue(
                    issue_type=ReviewIssueType.MISSING_CITATION,
                    severity=ReviewIssueSeverity.MINOR,
                    message="Section lacks inline citation markers in prose",
                    report_section_id=section.id,
                    finding_refs=section.finding_refs,
                ),
            )

    if not report.limitations:
        issues.append(
            _issue(
                issue_type=ReviewIssueType.MISSING_LIMITATION,
                severity=ReviewIssueSeverity.MAJOR,
                message="Report has no global limitations",
            ),
        )

    return tuple(issues)


def _issue(
    *,
    issue_type: ReviewIssueType,
    severity: ReviewIssueSeverity,
    message: str,
    report_section_id: str | None = None,
    finding_refs: tuple[str, ...] = (),
    research_question_refs: tuple[str, ...] = (),
) -> ReviewIssue:
    return ReviewIssue(
        id=str(uuid4()),
        issue_type=issue_type,
        severity=severity,
        message=message,
        report_section_id=report_section_id,
        finding_refs=finding_refs,
        research_question_refs=research_question_refs,
    )


def _contradictions_acknowledged(report: Report) -> bool:
    corpus = " ".join(
        [
            report.executive_summary,
            *(section.content for section in report.sections),
            *report.limitations,
        ],
    ).lower()
    if any(keyword in corpus for keyword in _ACK_KEYWORDS):
        return True
    return any(
        section.title == CONTRADICTION_SECTION_TITLE for section in report.sections
    )


def _rq_from_code(code: str) -> tuple[str, ...]:
    if ":" in code:
        return (code.split(":", 1)[1],)
    return ()


def compute_coverage_metrics_for_design(
    *,
    report: Report,
    design: ResearchDesign,
    findings: list[Finding],
    insights: list,
) -> tuple[dict, ...]:
    evidence_counts: dict[str, int] = {}
    for finding in findings:
        for rq in finding.research_question_refs:
            evidence_counts[rq] = evidence_counts.get(rq, 0) + len(finding.evidence_refs)
    return tuple(
        compute_rq_coverage_metrics(
            question=question,
            sections=report.sections,
            findings=findings,
            insights=insights,
            evidence_count=evidence_counts.get(question.id, 0),
        ).__dict__
        for question in design.research_questions
    )

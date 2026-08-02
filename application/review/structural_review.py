from __future__ import annotations

from uuid import uuid4

from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType
from domain.planning.research_design import ResearchDesign
from domain.reports.report import Report
from domain.research_brief import ResearchBrief
from domain.reviews.quality_dimension import (
    QualityDimension,
    QualityDimensionName,
    QualityDimensionStatus,
)
from domain.reviews.review_issue import (
    ReviewIssue,
    ReviewIssueSeverity,
    ReviewIssueType,
)
from domain.reviews.review_verdict import ReviewVerdict

from application.persistence.records import ArtifactRecord
from application.report.deduplication import compute_content_checksum
from application.review.exceptions import InvalidReviewProvenanceError


def run_structural_review(
    *,
    report: Report,
    brief: ResearchBrief,
    design: ResearchDesign,
    findings: list[Finding],
    artifact: ArtifactRecord | None = None,
) -> tuple[ReviewIssue, ...]:
    """Deterministic structural quality checks (DR-07)."""
    issues: list[ReviewIssue] = []

    if report.research_design_id != design.id:
        issues.append(
            _issue(
                ReviewIssueType.STRUCTURE_ISSUE,
                ReviewIssueSeverity.MAJOR,
                "Report research_design_id does not match workflow design snapshot",
            ),
        )

    if not report.executive_summary.strip():
        issues.append(
            _issue(
                ReviewIssueType.STRUCTURE_ISSUE,
                ReviewIssueSeverity.MAJOR,
                "Executive summary is required",
            ),
        )

    if not report.sections:
        issues.append(
            _issue(
                ReviewIssueType.STRUCTURE_ISSUE,
                ReviewIssueSeverity.MAJOR,
                "Report must contain at least one section",
            ),
        )

    registry = report.citation_registry or {}
    covered_questions: set[str] = set()
    for section in report.sections:
        if not section.finding_refs and not section.insight_refs:
            issues.append(
                _issue(
                    ReviewIssueType.STRUCTURE_ISSUE,
                    ReviewIssueSeverity.MAJOR,
                    f"Section '{section.title}' lacks Finding/Insight support",
                    report_section_id=section.id,
                ),
            )
        covered_questions.update(section.research_question_refs)
        for citation_id in section.citation_ids:
            if citation_id not in registry:
                issues.append(
                    _issue(
                        ReviewIssueType.MISSING_CITATION,
                        ReviewIssueSeverity.MAJOR,
                        f"Citation '{citation_id}' is not registered",
                        report_section_id=section.id,
                    ),
                )

    for question in design.research_questions:
        if question.id not in covered_questions:
            section_covers = any(
                question.id in section.research_question_refs
                or _section_supports_question(section, question.id, findings)
                for section in report.sections
            )
            if not section_covers:
                issues.append(
                    _issue(
                        ReviewIssueType.COVERAGE_GAP,
                        ReviewIssueSeverity.MAJOR,
                        f"Research question '{question.id}' is not covered in the report",
                        research_question_refs=(question.id,),
                    ),
                )

    if brief.objectives:
        for objective in brief.objectives:
            linked_questions = [
                question
                for question in design.research_questions
                if any(
                    objective.strip().lower() in ref.lower()
                    or ref.strip().lower() in objective.strip().lower()
                    for ref in question.objective_refs
                )
            ]
            if linked_questions and not any(
                question.id in covered_questions for question in linked_questions
            ):
                issues.append(
                    _issue(
                        ReviewIssueType.COVERAGE_GAP,
                        ReviewIssueSeverity.MAJOR,
                        f"Brief objective not covered via linked research questions: {objective[:80]}",
                    ),
                )

    contradiction_findings = [
        item for item in findings if item.finding_type == FindingType.CONTRADICTION
    ]
    if contradiction_findings and not _contradictions_acknowledged(
        report,
        contradiction_findings,
    ):
        issues.append(
            _issue(
                ReviewIssueType.CONTRADICTION,
                ReviewIssueSeverity.MAJOR,
                "Contradictory findings exist but are not acknowledged in the report",
                finding_refs=tuple(item.id for item in contradiction_findings),
            ),
        )

    if design.limitations:
        if not report.limitations:
            issues.append(
                _issue(
                    ReviewIssueType.MISSING_LIMITATION,
                    ReviewIssueSeverity.MAJOR,
                    "Report must include design limitations",
                ),
            )
        else:
            for limitation in design.limitations:
                if not _limitation_reflected(limitation, report.limitations):
                    issues.append(
                        _issue(
                            ReviewIssueType.MISSING_LIMITATION,
                            ReviewIssueSeverity.MINOR,
                            f"Design limitation not reflected: {limitation[:80]}",
                        ),
                    )

    if artifact is not None and artifact.report_id == report.id:
        rendered_checksum = artifact.content_checksum
        if rendered_checksum and artifact.content:
            actual = compute_content_checksum(artifact.content)
            if rendered_checksum != actual:
                issues.append(
                    _issue(
                        ReviewIssueType.STRUCTURE_ISSUE,
                        ReviewIssueSeverity.MAJOR,
                        "Artifact checksum does not match artifact content",
                    ),
                )

    marker = report.metadata.get("deterministic_review_flaw")
    if marker == "unsupported_claim":
        issues.append(
            _issue(
                ReviewIssueType.UNSUPPORTED_CLAIM,
                ReviewIssueSeverity.MAJOR,
                "Report contains an unsupported factual claim",
                suggested_action="Remove or support the claim with cited findings",
            ),
        )
    elif marker == "provenance_break":
        issues.append(
            _issue(
                ReviewIssueType.BRIEF_MISMATCH,
                ReviewIssueSeverity.MAJOR,
                "Report provenance is fundamentally broken",
            ),
        )

    if not findings:
        issues.append(
            _issue(
                ReviewIssueType.BRIEF_MISMATCH,
                ReviewIssueSeverity.MAJOR,
                "Insufficient findings to support a research report",
            ),
        )

    return tuple(issues)


def compute_quality_dimensions(
    issues: tuple[ReviewIssue, ...],
) -> tuple[QualityDimension, ...]:
    by_type: dict[QualityDimensionName, list[ReviewIssue]] = {
        name: [] for name in QualityDimensionName
    }
    for issue in issues:
        dimension = _dimension_for_issue(issue.issue_type)
        by_type[dimension].append(issue)

    dimensions: list[QualityDimension] = []
    for name in QualityDimensionName:
        related = by_type[name]
        if not related:
            dimensions.append(
                QualityDimension(name=name, status=QualityDimensionStatus.PASS),
            )
            continue
        if any(item.severity == ReviewIssueSeverity.MAJOR for item in related):
            dimensions.append(
                QualityDimension(
                    name=name,
                    status=QualityDimensionStatus.FAIL,
                    message=related[0].message,
                ),
            )
        else:
            dimensions.append(
                QualityDimension(
                    name=name,
                    status=QualityDimensionStatus.WARNING,
                    message=related[0].message,
                ),
            )
    return tuple(dimensions)


def compute_verdict(
    issues: tuple[ReviewIssue, ...],
) -> ReviewVerdict:
    if any(
        issue.issue_type == ReviewIssueType.BRIEF_MISMATCH
        and issue.severity == ReviewIssueSeverity.MAJOR
        for issue in issues
    ):
        return ReviewVerdict.REJECT

    if any(
        issue.issue_type == ReviewIssueType.STRUCTURE_ISSUE
        and "provenance" in issue.message.lower()
        for issue in issues
    ):
        return ReviewVerdict.REJECT

    major_issues = [
        issue for issue in issues if issue.severity == ReviewIssueSeverity.MAJOR
    ]
    if not major_issues:
        return ReviewVerdict.APPROVE

    reject_types = {
        ReviewIssueType.BRIEF_MISMATCH,
    }
    if any(issue.issue_type in reject_types for issue in major_issues):
        return ReviewVerdict.REJECT

    return ReviewVerdict.REVISE


def _dimension_for_issue(issue_type: ReviewIssueType) -> QualityDimensionName:
    mapping = {
        ReviewIssueType.COVERAGE_GAP: QualityDimensionName.BRIEF_COVERAGE,
        ReviewIssueType.BRIEF_MISMATCH: QualityDimensionName.BRIEF_COVERAGE,
        ReviewIssueType.MISSING_CITATION: QualityDimensionName.CITATION_COMPLETENESS,
        ReviewIssueType.UNSUPPORTED_CLAIM: QualityDimensionName.EVIDENCE_SUPPORT,
        ReviewIssueType.CONTRADICTION: QualityDimensionName.CONTRADICTION_HANDLING,
        ReviewIssueType.INCONSISTENT_ANALYSIS: QualityDimensionName.ANALYTICAL_CONSISTENCY,
        ReviewIssueType.MISSING_LIMITATION: QualityDimensionName.LIMITATIONS_COMPLETENESS,
        ReviewIssueType.STRUCTURE_ISSUE: QualityDimensionName.DELIVERABLE_COMPLIANCE,
    }
    if issue_type == ReviewIssueType.COVERAGE_GAP:
        return QualityDimensionName.RESEARCH_QUESTION_COVERAGE
    return mapping.get(issue_type, QualityDimensionName.DELIVERABLE_COMPLIANCE)


def _issue(
    issue_type: ReviewIssueType,
    severity: ReviewIssueSeverity,
    message: str,
    *,
    report_section_id: str | None = None,
    finding_refs: tuple[str, ...] = (),
    research_question_refs: tuple[str, ...] = (),
    suggested_action: str = "",
) -> ReviewIssue:
    return ReviewIssue(
        id=str(uuid4()),
        issue_type=issue_type,
        severity=severity,
        message=message,
        report_section_id=report_section_id,
        finding_refs=finding_refs,
        research_question_refs=research_question_refs,
        suggested_action=suggested_action,
    )


def _section_supports_question(
    section,
    question_id: str,
    findings: list[Finding],
) -> bool:
    if question_id in section.research_question_refs:
        return True
    finding_ids = set(section.finding_refs)
    return any(
        question_id in finding.research_question_refs
        for finding in findings
        if finding.id in finding_ids
    )


def _objective_reflected(objective: str, report: Report) -> bool:
    needle = objective.strip().lower()
    if not needle:
        return True
    corpus = " ".join(
        [
            report.executive_summary,
            *(section.content for section in report.sections),
        ],
    ).lower()
    tokens = [token for token in needle.split() if len(token) > 4]
    if not tokens:
        return needle in corpus
    return sum(token in corpus for token in tokens) >= min(2, len(tokens))


def _contradictions_acknowledged(report: Report, findings: list[Finding]) -> bool:
    corpus = " ".join(
        [
            report.executive_summary,
            *(section.content for section in report.sections),
            *report.limitations,
        ],
    ).lower()
    keywords = ("contradict", "conflict", "uncertain", "mixed", "inconsistent")
    if any(keyword in corpus for keyword in keywords):
        return True
    for finding in findings:
        if finding.statement.lower() in corpus:
            return True
    return False


def _limitation_reflected(limitation: str, report_limitations: tuple[str, ...]) -> bool:
    needle = limitation.strip().lower()
    if not needle:
        return True
    return any(needle in item.lower() or item.lower() in needle for item in report_limitations)

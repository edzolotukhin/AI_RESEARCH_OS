from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from domain.reports.report import Report
from domain.reviews.review_issue import (
    ReviewIssue,
    ReviewIssueSeverity,
    ReviewIssueType,
)

from application.ports.review_ports import (
    ReviewIssueCandidate,
    ReviewSectionInput,
    SemanticReviewInput,
)


class DeterministicReviewEngine:
    """Explicit test/smoke semantic reviewer — never used in production by default."""

    method_name = "deterministic"

    def review_report(
        self,
        review_input: SemanticReviewInput,
    ) -> tuple[ReviewIssueCandidate, ...]:
        issues: list[ReviewIssueCandidate] = []
        scenario = review_input.report.metadata.get("deterministic_review_scenario")

        for section_input in review_input.section_inputs:
            content = section_input.section_content
            if "UNSUPPORTED_CLAIM_MARKER" in content:
                issues.append(
                    ReviewIssueCandidate(
                        issue_type=ReviewIssueType.UNSUPPORTED_CLAIM.value,
                        severity=ReviewIssueSeverity.MAJOR.value,
                        message="Semantic reviewer flagged unsupported claim in section",
                        report_section_id=review_input.report.sections[
                            section_input.section_index
                        ].id,
                        suggested_action="Support or remove the unsupported claim",
                    ),
                )

        if scenario == "reject":
            issues.append(
                ReviewIssueCandidate(
                    issue_type=ReviewIssueType.BRIEF_MISMATCH.value,
                    severity=ReviewIssueSeverity.MAJOR.value,
                    message="Deterministic semantic reviewer rejected report",
                ),
            )

        return tuple(issues)


def candidates_to_issues(
    candidates: tuple[ReviewIssueCandidate, ...],
) -> tuple[ReviewIssue, ...]:
    issues: list[ReviewIssue] = []
    for candidate in candidates:
        issues.append(
            ReviewIssue(
                id=str(uuid4()),
                issue_type=ReviewIssueType(candidate.issue_type),
                severity=ReviewIssueSeverity(candidate.severity),
                message=candidate.message,
                report_section_id=candidate.report_section_id,
                finding_refs=candidate.finding_refs,
                insight_refs=candidate.insight_refs,
                evidence_refs=candidate.evidence_refs,
                source_refs=candidate.source_refs,
                research_question_refs=candidate.research_question_refs,
                suggested_action=candidate.suggested_action,
                metadata=dict(candidate.metadata),
            ),
        )
    return tuple(issues)


def build_section_inputs(
    report: Report,
    *,
    max_chars_per_section: int = 8000,
) -> tuple[ReviewSectionInput, ...]:
    return tuple(
        ReviewSectionInput(
            report=report,
            section_index=index,
            section_title=section.title,
            section_content=section.content[:max_chars_per_section],
            finding_refs=section.finding_refs,
            insight_refs=section.insight_refs,
            citation_ids=section.citation_ids,
            research_question_refs=section.research_question_refs,
        )
        for index, section in enumerate(report.sections)
    )

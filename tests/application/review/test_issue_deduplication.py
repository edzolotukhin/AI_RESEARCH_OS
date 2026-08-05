"""Review issue deduplication regression tests."""

from __future__ import annotations

import unittest
from uuid import uuid4

from domain.reviews.review_issue import (
    ReviewIssue,
    ReviewIssueSeverity,
    ReviewIssueType,
)
from domain.reviews.review_verdict import ReviewVerdict

from application.review.issue_deduplication import (
    deduplicate_review_issues,
    review_issue_semantic_key,
)
from application.review.structural_review import compute_verdict


def _issue(
    *,
    issue_type: ReviewIssueType,
    severity: ReviewIssueSeverity,
    message: str,
    section_id: str | None = None,
) -> ReviewIssue:
    return ReviewIssue(
        id=str(uuid4()),
        issue_type=issue_type,
        severity=severity,
        message=message,
        report_section_id=section_id,
    )


class ReviewIssueDeduplicationTests(unittest.TestCase):
    def test_duplicate_issues_across_sections_collapse(self) -> None:
        duplicate = _issue(
            issue_type=ReviewIssueType.UNSUPPORTED_CLAIM,
            severity=ReviewIssueSeverity.MINOR,
            message="Claim exceeds cited finding scope.",
        )
        issues = (
            _issue(
                issue_type=ReviewIssueType.UNSUPPORTED_CLAIM,
                severity=ReviewIssueSeverity.MINOR,
                message="Claim exceeds cited finding scope.",
                section_id="section-a",
            ),
            _issue(
                issue_type=ReviewIssueType.UNSUPPORTED_CLAIM,
                severity=ReviewIssueSeverity.MINOR,
                message="Claim  exceeds   cited finding scope.",
                section_id="section-b",
            ),
            duplicate,
        )
        deduped = deduplicate_review_issues(issues)
        self.assertEqual(len(deduped), 1)

    def test_distinct_issues_remain_distinct(self) -> None:
        issues = (
            _issue(
                issue_type=ReviewIssueType.UNSUPPORTED_CLAIM,
                severity=ReviewIssueSeverity.MINOR,
                message="Issue A",
            ),
            _issue(
                issue_type=ReviewIssueType.CONTRADICTION,
                severity=ReviewIssueSeverity.MINOR,
                message="Issue B",
            ),
        )
        self.assertEqual(len(deduplicate_review_issues(issues)), 2)

    def test_reject_verdict_preserved_after_dedup(self) -> None:
        issues = deduplicate_review_issues(
            (
                _issue(
                    issue_type=ReviewIssueType.BRIEF_MISMATCH,
                    severity=ReviewIssueSeverity.MAJOR,
                    message="Brief objective not reflected",
                ),
                _issue(
                    issue_type=ReviewIssueType.BRIEF_MISMATCH,
                    severity=ReviewIssueSeverity.MAJOR,
                    message="Brief objective not reflected",
                ),
            ),
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(compute_verdict(issues), ReviewVerdict.REJECT)

    def test_semantic_key_ignores_section_id(self) -> None:
        first = _issue(
            issue_type=ReviewIssueType.MISSING_CITATION,
            severity=ReviewIssueSeverity.MAJOR,
            message="Missing citation",
            section_id="s1",
        )
        second = _issue(
            issue_type=ReviewIssueType.MISSING_CITATION,
            severity=ReviewIssueSeverity.MAJOR,
            message="Missing citation",
            section_id="s2",
        )
        self.assertEqual(
            review_issue_semantic_key(first),
            review_issue_semantic_key(second),
        )


if __name__ == "__main__":
    unittest.main()

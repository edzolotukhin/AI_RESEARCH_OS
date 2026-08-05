from __future__ import annotations

import re

from domain.reviews.review_issue import ReviewIssue

_WHITESPACE = re.compile(r"\s+")


def normalize_review_message(message: str) -> str:
    return _WHITESPACE.sub(" ", message.strip().lower())


def review_issue_semantic_key(issue: ReviewIssue) -> tuple[str, ...]:
    return (
        issue.issue_type.value,
        issue.severity.value,
        normalize_review_message(issue.message),
        tuple(sorted(issue.finding_refs)),
        tuple(sorted(issue.insight_refs)),
        tuple(sorted(issue.evidence_refs)),
        tuple(sorted(issue.source_refs)),
        tuple(sorted(issue.research_question_refs)),
    )


def deduplicate_review_issues(
    issues: tuple[ReviewIssue, ...] | list[ReviewIssue],
) -> tuple[ReviewIssue, ...]:
    """Collapse duplicate semantic issues produced across per-section review calls."""
    seen: set[tuple[str, ...]] = set()
    unique: list[ReviewIssue] = []
    for issue in issues:
        key = review_issue_semantic_key(issue)
        if key in seen:
            continue
        seen.add(key)
        unique.append(issue)
    return tuple(unique)

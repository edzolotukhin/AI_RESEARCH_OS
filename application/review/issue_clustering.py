from __future__ import annotations

import re
from uuid import uuid4

from domain.reviews.review_issue import ReviewIssue

from application.review.issue_deduplication import normalize_review_message

_THEME_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "contradiction_not_acknowledged",
        re.compile(
            r"contradict|conflict|not acknowledged|not reconcil|uncertain",
            re.IGNORECASE,
        ),
    ),
    (
        "missing_inline_citation",
        re.compile(
            r"missing citation|lack.*citation|explicit linkage|inline citation",
            re.IGNORECASE,
        ),
    ),
    (
        "unsupported_numeric_claim",
        re.compile(
            r"unsupported|without evidence|otif|kpi|>=|<=|prescriptive",
            re.IGNORECASE,
        ),
    ),
    (
        "missing_contextual_limitation",
        re.compile(
            r"missing limitation|no caveat|lacks concrete caveat",
            re.IGNORECASE,
        ),
    ),
    (
        "substantive_coverage_gap",
        re.compile(
            r"coverage gap|does not address|not address|pricing|regulatory",
            re.IGNORECASE,
        ),
    ),
)


def normalize_issue_theme(message: str, issue_type: str) -> str:
    for theme, pattern in _THEME_PATTERNS:
        if pattern.search(message):
            return theme
    return f"{issue_type}_other"


def review_issue_cluster_key(issue: ReviewIssue) -> tuple[str, ...]:
    """Stable identity: type + severity + theme + RQ refs (message excluded)."""
    return (
        issue.issue_type.value,
        issue.severity.value,
        normalize_issue_theme(issue.message, issue.issue_type.value),
        tuple(sorted(issue.research_question_refs)),
    )


def cluster_review_issues(
    issues: tuple[ReviewIssue, ...] | list[ReviewIssue],
) -> tuple[ReviewIssue, ...]:
    """Collapse semantically equivalent issues; aggregate section refs in metadata."""
    clusters: dict[tuple[str, ...], ReviewIssue] = {}
    section_ids_by_key: dict[tuple[str, ...], set[str]] = {}

    for issue in issues:
        key = review_issue_cluster_key(issue)
        if issue.report_section_id:
            section_ids_by_key.setdefault(key, set()).add(issue.report_section_id)
        existing = clusters.get(key)
        if existing is None:
            clusters[key] = issue
            continue
        # Keep the shorter canonical message for global issues
        if len(issue.message) < len(existing.message):
            clusters[key] = issue

    result: list[ReviewIssue] = []
    for key, issue in clusters.items():
        affected = sorted(section_ids_by_key.get(key, set()))
        metadata = dict(issue.metadata or {})
        if affected:
            metadata["affected_section_ids"] = affected
            metadata["cluster_count"] = len(affected)
        result.append(
            ReviewIssue(
                id=issue.id,
                issue_type=issue.issue_type,
                severity=issue.severity,
                message=issue.message,
                report_section_id=issue.report_section_id,
                finding_refs=issue.finding_refs,
                insight_refs=issue.insight_refs,
                evidence_refs=issue.evidence_refs,
                source_refs=issue.source_refs,
                research_question_refs=issue.research_question_refs,
                suggested_action=issue.suggested_action,
                metadata=metadata,
            ),
        )
    return tuple(result)


def deduplicate_and_cluster_review_issues(
    issues: tuple[ReviewIssue, ...] | list[ReviewIssue],
) -> tuple[ReviewIssue, ...]:
    from application.review.issue_deduplication import deduplicate_review_issues

    deduped = deduplicate_review_issues(issues)
    return cluster_review_issues(deduped)

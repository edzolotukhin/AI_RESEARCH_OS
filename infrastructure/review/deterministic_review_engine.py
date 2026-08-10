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


@dataclass(frozen=True)
class ReviewBatchInput:
    batch_id: str
    batch_label: str
    section_indices: tuple[int, ...]
    section_content: str
    finding_refs: tuple[str, ...]
    insight_refs: tuple[str, ...]
    citation_ids: tuple[str, ...]
    research_question_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewBatchPlan:
    """RQ-batch plan with explicit omitted groups for fail-closed coverage."""

    batches: tuple[ReviewBatchInput, ...]
    omitted_batch_ids: tuple[str, ...]
    total_group_count: int


def build_rq_batch_inputs(
    report: Report,
    *,
    max_chars_per_section: int = 8000,
    max_chars_per_batch: int = 12000,
    max_batches: int = 7,
) -> ReviewBatchPlan:
    """Group sections by primary RQ + global batch; enforce section + batch bounds."""
    from application.report.substantive_coverage import primary_research_question_for_section

    groups: dict[str, list[int]] = {}
    for index, section in enumerate(report.sections):
        primary = primary_research_question_for_section(section)
        key = primary or "__global__"
        groups.setdefault(key, []).append(index)

    ordered_groups = sorted(groups.items())
    batches: list[ReviewBatchInput] = []
    omitted: list[str] = []
    for batch_id, indices in ordered_groups:
        if len(batches) >= max_batches:
            omitted.append(batch_id)
            continue
        sections = [report.sections[i] for i in indices]
        per_section_budget = min(
            max_chars_per_section,
            max(1, max_chars_per_batch // max(1, len(indices))),
        )
        content_parts = [
            f"## {section.title}\n{section.content[:per_section_budget]}"
            for section in sections
        ]
        finding_refs: set[str] = set()
        insight_refs: set[str] = set()
        citation_ids: set[str] = set()
        rq_refs: set[str] = set()
        for section in sections:
            finding_refs.update(section.finding_refs)
            insight_refs.update(section.insight_refs)
            citation_ids.update(section.citation_ids)
            rq_refs.update(section.research_question_refs)
        label = batch_id if batch_id != "__global__" else "global_report"
        batches.append(
            ReviewBatchInput(
                batch_id=batch_id,
                batch_label=label,
                section_indices=tuple(indices),
                section_content="\n\n".join(content_parts)[:max_chars_per_batch],
                finding_refs=tuple(sorted(finding_refs)),
                insight_refs=tuple(sorted(insight_refs)),
                citation_ids=tuple(sorted(citation_ids)),
                research_question_refs=tuple(sorted(rq_refs)),
            ),
        )
    return ReviewBatchPlan(
        batches=tuple(batches),
        omitted_batch_ids=tuple(omitted),
        total_group_count=len(ordered_groups),
    )

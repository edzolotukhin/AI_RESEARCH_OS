from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from domain.reports.report import Report
from domain.reviews.review_issue import ReviewIssue
from domain.reviews.review_result import ReviewResult


@dataclass(frozen=True)
class ReviewSectionInput:
    report: Report
    section_index: int
    section_title: str
    section_content: str
    finding_refs: tuple[str, ...]
    insight_refs: tuple[str, ...]
    citation_ids: tuple[str, ...]
    research_question_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewIssueCandidate:
    issue_type: str
    severity: str
    message: str
    report_section_id: str | None = None
    finding_refs: tuple[str, ...] = ()
    insight_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    research_question_refs: tuple[str, ...] = ()
    suggested_action: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SemanticReviewInput:
    project_id: str
    workflow_run_id: str
    research_design_id: str
    report: Report
    brief_objectives: tuple[str, ...]
    research_questions: tuple[str, ...]
    section_inputs: tuple[ReviewSectionInput, ...]
    existing_issues: tuple[ReviewIssue, ...] = ()


class SemanticReviewEngine(Protocol):
    method_name: str

    def review_report(
        self,
        review_input: SemanticReviewInput,
    ) -> tuple[ReviewIssueCandidate, ...]:
        ...


class ReviewRepository(Protocol):
    def create(self, review: ReviewResult) -> int:
        ...

    def get_by_id(self, review_id: str) -> ReviewResult | None:
        ...

    def get_by_deduplication_key(
        self,
        workflow_run_id: str,
        deduplication_key: str,
    ) -> ReviewResult | None:
        ...

    def list_for_project(
        self,
        project_id: str,
        *,
        workflow_run_id: str | None = None,
        report_id: str | None = None,
        verdict: str | None = None,
    ) -> list[ReviewResult]:
        ...

    def count_for_run(self, project_id: str, workflow_run_id: str) -> int:
        ...

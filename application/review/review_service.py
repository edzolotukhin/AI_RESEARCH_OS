from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from domain.reports.report import Report
from domain.reviews.review_result import ReviewResult
from domain.reviews.review_verdict import ReviewVerdict

from application.persistence.exceptions import ConcurrentModificationError
from application.persistence.records import ArtifactRecord
from application.ports.analysis_ports import FindingRepository, InsightRepository
from application.ports.artifact_repository import ArtifactRepository
from application.ports.evidence_ports import EvidenceRepository
from application.ports.report_ports import ReportRepository
from application.ports.review_ports import (
    ReviewRepository,
    SemanticReviewEngine,
    SemanticReviewInput,
)
from application.report.exceptions import ReportError
from application.report.report_service import ReportService
from application.review.deduplication import compute_review_deduplication_key
from application.review.deterministic_pre_review import run_deterministic_pre_review
from application.review.issue_clustering import deduplicate_and_cluster_review_issues
from application.review.diagnostics import (
    ReviewFailureDiagnostics,
    ReviewSectionDiagnostics,
    format_review_parse_failure_message,
)
from application.review.exceptions import (
    DuplicateReviewError,
    ReviewConfigurationError,
    ReviewError,
)
from application.review.review_support_context import (
    build_review_support_context,
    incomplete_review_coverage_issue,
    support_reference_issues,
)
from application.review.structural_review import (
    compute_quality_dimensions,
    compute_verdict,
    run_structural_review,
)
from infrastructure.review.deterministic_review_engine import (
    build_section_inputs,
    candidates_to_issues,
)
from infrastructure.review.llm_review_engine import LlmReviewEngine

from application.execution.exceptions import BudgetExhaustedError
from runtime.workflow_context import WorkflowContext

logger = logging.getLogger("ai_research_os.review")

_MAX_DEDUP_RETRIES = 5


@dataclass(frozen=True)
class ReviewSummary:
    review_id: str
    verdict: str
    report_id: str
    artifact_id: str | None
    review_attempt: int
    revision_count: int
    issue_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "verdict": self.verdict,
            "report_id": self.report_id,
            "artifact_id": self.artifact_id,
            "review_attempt": self.review_attempt,
            "revision_count": self.revision_count,
            "issue_count": self.issue_count,
        }


class ReviewService:
    """Independent report quality gate with bounded revision loop (DR-07)."""

    def __init__(
        self,
        *,
        semantic_review_engine: SemanticReviewEngine,
        finding_repository: FindingRepository,
        insight_repository: InsightRepository,
        evidence_repository: EvidenceRepository,
        report_repository: ReportRepository,
        artifact_repository: ArtifactRepository,
        review_repository: ReviewRepository,
        report_service: ReportService,
        max_revision_attempts: int,
        max_chars_per_section: int = 8000,
    ) -> None:
        self._semantic_review_engine = semantic_review_engine
        self._finding_repository = finding_repository
        self._insight_repository = insight_repository
        self._evidence_repository = evidence_repository
        self._report_repository = report_repository
        self._artifact_repository = artifact_repository
        self._review_repository = review_repository
        self._report_service = report_service
        self._max_revision_attempts = max_revision_attempts
        self._max_chars_per_section = max_chars_per_section
        self._last_support_diagnostics: dict[str, Any] = {}

    def review_for_context(self, context: WorkflowContext) -> ReviewSummary:
        design = self._report_service._resolve_design(context)
        brief = self._report_service._resolve_brief(context)
        project_id = context.project.id
        workflow_run_id = context.workflow_run.id

        revision_count = 0
        review_attempt = 0

        while True:
            review_attempt += 1
            report = self._latest_report(project_id, workflow_run_id)
            if report is None:
                raise ReviewError(
                    f"No report available for review in run {workflow_run_id}",
                )

            artifact = self._artifact_for_report(workflow_run_id, report.id)
            findings = self._finding_repository.list_for_project(
                project_id,
                workflow_run_id=workflow_run_id,
            )
            insights = self._insight_repository.list_for_project(
                project_id,
                workflow_run_id=workflow_run_id,
            )
            evidence_items = self._evidence_repository.list_for_project(
                project_id,
                workflow_run_id=workflow_run_id,
            )
            # Run/design isolation: drop any foreign records that leaked into lists.
            findings = [
                item
                for item in findings
                if item.workflow_run_id == workflow_run_id
                and item.research_design_id == design.id
                and item.project_id == project_id
            ]
            insights = [
                item
                for item in insights
                if item.workflow_run_id == workflow_run_id
                and item.research_design_id == design.id
                and item.project_id == project_id
            ]
            evidence_items = [
                item
                for item in evidence_items
                if item.workflow_run_id == workflow_run_id
                and item.research_design_id == design.id
                and item.project_id == project_id
            ]

            support_context = build_review_support_context(
                report=report,
                findings=findings,
                insights=insights,
                evidence_items=evidence_items,
            )
            support_issues = support_reference_issues(support_context)
            self._last_support_diagnostics = dict(support_context.diagnostics)

            pre_review_issues = run_deterministic_pre_review(
                report=report,
                design=design,
                findings=findings,
                insights=insights,
            )

            structural_issues = run_structural_review(
                report=report,
                brief=brief,
                design=design,
                findings=findings,
                artifact=artifact,
            )

            semantic_candidates = self._run_semantic_review(
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                design_id=design.id,
                report=report,
                brief_objectives=brief.objectives,
                research_questions=tuple(
                    question.question for question in design.research_questions
                ),
                structural_issues=structural_issues,
                support_context=support_context,
            )
            coverage_issues = self._incomplete_coverage_issues()
            all_issues = deduplicate_and_cluster_review_issues(
                pre_review_issues
                + structural_issues
                + support_issues
                + coverage_issues
                + candidates_to_issues(semantic_candidates),
            )
            dimensions = compute_quality_dimensions(all_issues)
            verdict = compute_verdict(all_issues)

            review_id = self._persist_review(
                ReviewResult(
                    id=str(uuid4()),
                    project_id=project_id,
                    workflow_run_id=workflow_run_id,
                    research_design_id=design.id,
                    report_id=report.id,
                    artifact_id=artifact.id if artifact is not None else None,
                    previous_report_id=report.previous_report_id,
                    review_attempt=review_attempt,
                    verdict=verdict,
                    quality_dimensions=dimensions,
                    issues=all_issues,
                    summary=self._build_summary(verdict, all_issues),
                    review_method=self._semantic_review_engine.method_name,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    deduplication_key=compute_review_deduplication_key(
                        workflow_run_id=workflow_run_id,
                        report_id=report.id,
                        review_attempt=review_attempt,
                    ),
                ),
                workflow_run_id=workflow_run_id,
            )

            if verdict == ReviewVerdict.APPROVE:
                approved_artifact_id = self._approve_artifact(report, artifact)
                return ReviewSummary(
                    review_id=review_id,
                    verdict=verdict.value,
                    report_id=report.id,
                    artifact_id=approved_artifact_id,
                    review_attempt=review_attempt,
                    revision_count=revision_count,
                    issue_count=len(all_issues),
                )

            if verdict == ReviewVerdict.REJECT:
                self._reject_artifact(artifact)
                raise ReviewError(
                    f"Report rejected by quality gate for run {workflow_run_id}",
                )

            if revision_count >= self._max_revision_attempts:
                self._reject_artifact(artifact)
                raise ReviewError(
                    f"Review revision attempts exhausted for run {workflow_run_id}",
                )

            review_result = self._review_repository.get_by_id(review_id)
            if review_result is None:
                raise ReviewError(f"Review record missing after persist: {review_id}")

            self._report_service.revise_for_context(context, review_result=review_result)
            revision_count += 1

    def _run_semantic_review(
        self,
        *,
        project_id: str,
        workflow_run_id: str,
        design_id: str,
        report: Report,
        brief_objectives: tuple[str, ...],
        research_questions: tuple[str, ...],
        structural_issues: tuple,
        support_context,
    ):
        section_inputs = build_section_inputs(
            report,
            max_chars_per_section=self._max_chars_per_section,
        )
        review_input = SemanticReviewInput(
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            research_design_id=design_id,
            report=report,
            brief_objectives=brief_objectives,
            research_questions=research_questions,
            section_inputs=section_inputs,
            existing_issues=structural_issues,
            support_context=support_context,
        )
        try:
            return self._semantic_review_engine.review_report(review_input)
        except BudgetExhaustedError as exc:
            raise ReviewError(str(exc)) from exc
        except ReviewConfigurationError as exc:
            diagnostics = self._build_parse_failure_diagnostics(
                workflow_run_id=workflow_run_id,
                section_inputs=section_inputs,
            )
            logger.error(
                "review_structured_output_failed run_id=%s diagnostics=%s",
                workflow_run_id,
                diagnostics.to_dict(),
            )
            raise ReviewError(
                format_review_parse_failure_message(diagnostics),
            ) from exc

    def _incomplete_coverage_issues(self) -> tuple:
        engine = self._semantic_review_engine
        if not isinstance(engine, LlmReviewEngine):
            return ()
        plan = engine.last_batch_plan
        if plan is None or not plan.omitted_batch_ids:
            return ()
        issue = incomplete_review_coverage_issue(
            omitted_batch_ids=plan.omitted_batch_ids,
            max_batches=engine._max_review_calls,
        )
        self._last_support_diagnostics = {
            **self._last_support_diagnostics,
            "incomplete_review_coverage": True,
            "omitted_batch_ids": list(plan.omitted_batch_ids),
            "semantic_batches": len(plan.batches),
            "total_group_count": plan.total_group_count,
            "review_calls_used": engine.llm_call_count,
        }
        return (issue,)

    def _build_parse_failure_diagnostics(
        self,
        *,
        workflow_run_id: str,
        section_inputs,
    ) -> ReviewFailureDiagnostics:
        engine = self._semantic_review_engine
        sections: list[ReviewSectionDiagnostics] = []
        if isinstance(engine, LlmReviewEngine):
            for index, section_input in enumerate(section_inputs):
                stats = (
                    engine.section_stats[index]
                    if index < len(engine.section_stats)
                    else engine.last_section_stats
                )
                if stats is None:
                    continue
                sections.append(
                    ReviewSectionDiagnostics(
                        section_id=section_input.section_title,
                        section_index=index,
                        candidate_review_count=stats.candidate_review_count,
                        parse_failure_category=stats.parse_failure_category,
                        contract_failure_category=stats.contract_failure_category,
                        output_tokens=stats.output_tokens,
                        reasoning_tokens=stats.reasoning_tokens,
                        visible_output_length=stats.visible_output_length,
                        finish_reason=stats.finish_reason,
                        max_output_tokens=stats.max_output_tokens,
                        reasoning_effort=stats.reasoning_effort,
                        attempts=stats.attempts,
                    ),
                )
        return ReviewFailureDiagnostics(
            workflow_run_id=workflow_run_id,
            section_count=len(section_inputs),
            section_failures=max(1, len(sections)),
            sections=sections,
        )

    def _latest_report(self, project_id: str, workflow_run_id: str) -> Report | None:
        reports = self._report_repository.list_for_project(
            project_id,
            workflow_run_id=workflow_run_id,
        )
        if not reports:
            return None
        return max(reports, key=lambda item: item.revision_number)

    def _artifact_for_report(
        self,
        workflow_run_id: str,
        report_id: str,
    ) -> ArtifactRecord | None:
        for artifact in self._artifact_repository.list_for_run(workflow_run_id):
            if artifact.report_id == report_id:
                return artifact
        artifacts = self._artifact_repository.list_for_run(workflow_run_id)
        return artifacts[0] if artifacts else None

    def _persist_review(self, review: ReviewResult, *, workflow_run_id: str) -> str:
        existing = self._review_repository.get_by_deduplication_key(
            workflow_run_id,
            review.deduplication_key,
        )
        if existing is not None:
            return existing.id

        for _ in range(_MAX_DEDUP_RETRIES):
            try:
                self._review_repository.create(review)
                return review.id
            except DuplicateReviewError:
                existing = self._review_repository.get_by_deduplication_key(
                    workflow_run_id,
                    review.deduplication_key,
                )
                if existing is not None:
                    return existing.id

        raise ReviewError(
            f"Failed to resolve concurrent review persistence for run {workflow_run_id}",
        )

    def _approve_artifact(
        self,
        report: Report,
        artifact: ArtifactRecord | None,
    ) -> str | None:
        if artifact is None:
            return None
        updated = ArtifactRecord(
            id=artifact.id,
            project_id=artifact.project_id,
            artifact_type=artifact.artifact_type,
            title=artifact.title,
            content=artifact.content,
            run_id=artifact.run_id,
            status="approved",
            version=artifact.version,
            media_type=artifact.media_type,
            filename=artifact.filename,
            content_checksum=artifact.content_checksum,
            deduplication_key=artifact.deduplication_key,
            report_id=report.id,
        )
        try:
            self._artifact_repository.save(updated, expected_version=artifact.version)
        except ConcurrentModificationError:
            current = self._artifact_repository.get_by_id(artifact.id)
            if current is not None and current.status == "approved":
                return artifact.id
            raise
        return artifact.id

    def _reject_artifact(self, artifact: ArtifactRecord | None) -> None:
        if artifact is None:
            return
        for _ in range(3):
            current = self._artifact_repository.get_by_id(artifact.id)
            if current is None:
                return
            if current.status == "rejected":
                return
            updated = ArtifactRecord(
                id=current.id,
                project_id=current.project_id,
                artifact_type=current.artifact_type,
                title=current.title,
                content=current.content,
                run_id=current.run_id,
                status="rejected",
                version=current.version,
                media_type=current.media_type,
                filename=current.filename,
                content_checksum=current.content_checksum,
                deduplication_key=current.deduplication_key,
                report_id=current.report_id,
            )
            try:
                self._artifact_repository.save(updated, expected_version=current.version)
                return
            except ConcurrentModificationError:
                continue

    @staticmethod
    def _build_summary(verdict: ReviewVerdict, issues: tuple) -> str:
        if verdict == ReviewVerdict.APPROVE:
            return "Report passed quality gate"
        if not issues:
            return f"Review verdict: {verdict.value}"
        return f"{verdict.value}: {issues[0].message}"

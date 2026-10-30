from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from application.deliverables.desk_finalization import coverage_contract_digest
from application.ports.report_ports import ReportRepository
from application.ports.report_claim_repository import ReportClaimRepository
from application.ports.review_ports import ReviewRepository
from application.report.contract_selection import H3_REPORT_CONTRACT
from application.report.h3_editorial_delivery import (
    H3ReviewDecision, H3PresentationEnvelope, run_h3_review_once,
)
from application.review.deduplication import compute_review_deduplication_key
from application.review.exceptions import ReviewError
from application.review.review_service import ReviewSummary, _MAX_DEDUP_RETRIES
from application.review.h3_review_branch import h3_review_round
from domain.reviews.review_issue import ReviewIssue, ReviewIssueSeverity, ReviewIssueType
from domain.reviews.review_result import ReviewResult
from domain.reviews.review_verdict import ReviewVerdict
from runtime.workflow_context import WorkflowContext


class H3WorkflowReviewAdapter:
    """Durable adapter for one H3 structural Review decision."""

    contract_version = H3_REPORT_CONTRACT

    def __init__(
        self, *, report_repository: ReportRepository,
        report_claim_repository: ReportClaimRepository,
        review_repository: ReviewRepository,
        review_provider,
    ) -> None:
        self._reports = report_repository
        self._claims = report_claim_repository
        self._reviews = review_repository
        self._provider = review_provider

    def review_for_context(self, context: WorkflowContext) -> ReviewSummary:
        run_id = context.workflow_run.id
        project_id = context.project.id
        report = self._latest_report(project_id, run_id)
        if report is None:
            raise ReviewError(f"No report available for H3 review in run {run_id}")
        claims = tuple(self._claims.list_for_report(report.id, report.revision_number))
        raw = report.metadata.get("h3_presentation")
        if not isinstance(raw, dict):
            raise ReviewError("H3 presentation is not persisted")
        try:
            presentation = H3PresentationEnvelope.from_dict(raw)
        except Exception as exc:
            raise ReviewError("Invalid persisted H3 presentation") from exc
        self._validate_state(report, presentation, context)
        attempt = self._next_attempt(project_id, run_id, report.id)
        dedup = compute_review_deduplication_key(
            workflow_run_id=run_id, report_id=report.id, review_attempt=attempt,
        )
        existing = self._reviews.get_by_deduplication_key(run_id, dedup)
        if existing is not None:
            self._validate_persisted(existing, report, presentation, context)
            return self._summary(existing)
        if self._provider is None:
            raise ReviewError("H3 Review provider is not configured")
        result = run_h3_review_once(
            report=report, claims=claims, presentation=presentation,
            coverage_contract_digest=presentation.coverage_contract_digest,
            review_provider=self._provider,
        )
        verdict = {
            H3ReviewDecision.APPROVE: ReviewVerdict.APPROVE,
            H3ReviewDecision.REVISE: ReviewVerdict.REVISE,
            H3ReviewDecision.REJECT: ReviewVerdict.REJECT,
        }[result.decision]
        issues = tuple(self._issue(item, report, claims) for item in result.issues)
        round_number = h3_review_round(context)
        if round_number is None:
            raise ReviewError("H3 Review task round is invalid")
        metadata = self._metadata(report, presentation, result, attempt, round_number)
        review = ReviewResult(
            id=str(uuid4()), project_id=project_id, workflow_run_id=run_id,
            research_design_id=report.research_design_id, report_id=report.id,
            review_attempt=attempt, verdict=verdict, quality_dimensions=(),
            issues=issues, summary=f"H3 structural Review: {verdict.value}",
            review_method="h3-structural", created_at=datetime.now(timezone.utc).isoformat(),
            deduplication_key=dedup, metadata=metadata,
        )
        for _ in range(_MAX_DEDUP_RETRIES):
            try:
                self._reviews.create(review)
                return self._summary(review)
            except Exception:
                existing = self._reviews.get_by_deduplication_key(run_id, dedup)
                if existing is not None:
                    self._validate_persisted(existing, report, presentation, context)
                    return self._summary(existing)
        raise ReviewError("Failed to resolve concurrent H3 Review persistence")

    def _validate_state(self, report, presentation, context) -> None:
        if report.metadata.get("structured_claim_contract") != H3_REPORT_CONTRACT:
            raise ReviewError("H3 Review received a non-H3 Report")
        if presentation.report_id != report.id or presentation.revision_number != report.revision_number:
            raise ReviewError("H3 Review presentation identity mismatch")
        if presentation.report_workflow_run_id != report.workflow_run_id:
            raise ReviewError("H3 Review report lineage mismatch")
        from application.report.h3_editorial_delivery import deterministic_h3_pre_review
        deterministic_h3_pre_review(
            report=report,
            claims=tuple(self._claims.list_for_report(report.id, report.revision_number)),
            presentation=presentation,
            coverage_contract_digest=presentation.coverage_contract_digest,
        )

    def _validate_persisted(self, review, report, presentation, context) -> None:
        metadata = review.metadata
        required = {
            "report_contract_version": H3_REPORT_CONTRACT,
            "report_id": report.id,
            "report_revision": report.revision_number,
            "report_workflow_run_id": report.workflow_run_id,
            "source_workflow_run_id": presentation.source_workflow_run_id,
            "authority_digest": presentation.authority_digest,
            "presentation_digest": presentation.presentation_digest,
            "review_round": h3_review_round(context),
        }
        if any(metadata.get(key) != value for key, value in required.items()):
            raise ReviewError("Persisted H3 Review provenance mismatch")
        if review.report_id != report.id or not isinstance(review.verdict, ReviewVerdict):
            raise ReviewError("Persisted H3 Review identity mismatch")

    @staticmethod
    def _issue(item: Any, report, claims) -> ReviewIssue:
        if not isinstance(item, dict):
            item = {"message": str(item)}
        severity = ReviewIssueSeverity.MAJOR if str(item.get("severity", "major")).lower() == "major" else ReviewIssueSeverity.MINOR
        claim_ids = tuple(str(value) for value in item.get("claim_refs", ()) if value)
        return ReviewIssue(
            id=str(item.get("id") or uuid4()), issue_type=ReviewIssueType.STRUCTURE_ISSUE,
            severity=severity, message=str(item.get("message", "H3 editorial issue"))[:2000],
            claim_refs=claim_ids, report_revision=report.revision_number,
            suggested_action=str(item.get("suggested_action", ""))[:500],
            metadata={"h3": True, "target": str(item.get("target", ""))[:128]},
        )

    @staticmethod
    def _metadata(report, presentation, result, attempt, round_number) -> dict[str, Any]:
        return {
            "report_contract_version": H3_REPORT_CONTRACT,
            "structured_claim_contract": H3_REPORT_CONTRACT,
            "h3_review_contract": "desk_h3_review_v1",
            "report_id": report.id, "report_revision": report.revision_number,
            "report_workflow_run_id": report.workflow_run_id,
            "source_workflow_run_id": presentation.source_workflow_run_id,
            "authority_digest": presentation.authority_digest,
            "presentation_digest": presentation.presentation_digest,
            "typed_ast_digest": presentation.ast_digest,
            "claim_set_digest": presentation.claim_set_digest,
            "coverage_contract_digest": presentation.coverage_contract_digest,
            "decision": result.decision.value, "review_attempt": attempt,
            "review_round": round_number,
            "provider_call_count": result.provider_call_count,
            "review_implementation": "h3_workflow_review_adapter_v1",
        }

    @staticmethod
    def _summary(review) -> ReviewSummary:
        return ReviewSummary(
            review_id=review.id, verdict=review.verdict.value, report_id=review.report_id,
            artifact_id=review.artifact_id, review_attempt=review.review_attempt,
            revision_count=max(0, review.review_attempt - 1), issue_count=len(review.issues),
        )

    def _latest_report(self, project_id, workflow_run_id):
        reports = self._reports.list_for_project(project_id, workflow_run_id=workflow_run_id)
        return max(reports, key=lambda item: item.revision_number) if reports else None

    def _next_attempt(self, project_id, workflow_run_id, report_id) -> int:
        reviews = self._reviews.list_for_project(project_id, workflow_run_id=workflow_run_id, report_id=report_id)
        return max((item.review_attempt for item in reviews), default=0) + 1

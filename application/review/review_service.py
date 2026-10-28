from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from domain.reports.report import Report
from domain.reviews.review_result import ReviewResult
from domain.reviews.review_verdict import ReviewVerdict

from application.persistence.exceptions import ConcurrentModificationError
from application.evidence.temporal_scope import qualifying_evidence
from application.persistence.records import ArtifactRecord
from application.ports.analysis_ports import FindingRepository, InsightRepository
from application.ports.artifact_repository import ArtifactRepository
from application.ports.evidence_ports import EvidenceRepository
from application.ports.report_ports import ReportRepository
from application.ports.report_claim_repository import ReportClaimRepository
from application.deliverables.desk_finalization import claim_set_digest, coverage_contract_digest
from application.ports.review_ports import (
    ReviewRepository,
    ReviewIssueCandidate,
    SemanticReviewEngine,
    SemanticReviewInput,
)
from application.report.exceptions import ReportError
from application.report.editorial_contract import EDITORIAL_CONTRACT_VERSION
from application.report.presentation_persistence import PresentationPersistenceError
from application.report.coverage_contract import (
    CoverageContractError,
    required_research_question_texts,
    resolve_report_coverage_contract,
)
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
from application.review.claim_review import review_structured_claim_contract
from application.review.presentation_review import (
    MAX_FULL_REPORT_LIFECYCLE_CALLS,
    PresentationReviewError,
    build_presentation_review_input,
    deterministic_presentation_issues,
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
        report_claim_repository: ReportClaimRepository | None = None,
    ) -> None:
        self._semantic_review_engine = semantic_review_engine
        self._finding_repository = finding_repository
        self._insight_repository = insight_repository
        self._evidence_repository = evidence_repository
        self._report_repository = report_repository
        self._report_claim_repository = report_claim_repository
        self._artifact_repository = artifact_repository
        self._review_repository = review_repository
        self._report_service = report_service
        self._max_revision_attempts = max_revision_attempts
        self._max_chars_per_section = max_chars_per_section
        self._last_support_diagnostics: dict[str, Any] = {}

    def review_for_context(self, context: WorkflowContext) -> ReviewSummary:
        workflow_run_id = context.workflow_run.id
        from application.replay.desk_downstream_replay import source_run_id
        artifact_run_id = source_run_id(context)
        self._set_review_diagnostics(context, phase="entry", status="started")
        try:
            design = self._report_service._resolve_design(context)
            brief = self._report_service._resolve_brief(context)
        except Exception:
            self._set_review_diagnostics(context, phase="entry", status="failed", category="other")
            raise
        project_id = context.project.id

        revision_count = 0
        review_attempt = 0

        while True:
            review_attempt += 1
            report = self._latest_report(project_id, workflow_run_id)
            if report is None:
                self._set_review_diagnostics(
                    context, phase="precheck", status="failed", category="deterministic_precheck_rejection"
                )
                raise ReviewError(
                    f"No report available for review in run {workflow_run_id}",
                )
            if (
                report.project_id != project_id
                or report.workflow_run_id != workflow_run_id
                or report.research_design_id != design.id
            ):
                self._set_review_diagnostics(
                    context, phase="coverage_contract", status="failed",
                    category="structural_validation_rejection",
                    rejection_codes=("coverage_contract_lineage_mismatch",),
                )
                raise ReviewError("Report coverage contract lineage mismatch")
            try:
                coverage_contract = resolve_report_coverage_contract(
                    report=report, design=design,
                )
            except CoverageContractError as exc:
                self._set_review_diagnostics(
                    context, phase="coverage_contract", status="failed",
                    category="structural_validation_rejection",
                    rejection_codes=exc.codes,
                )
                raise ReviewError("Invalid Report RQ coverage contract") from exc

            editorial = report.metadata.get("report_contract_version") == EDITORIAL_CONTRACT_VERSION

            artifact = None if editorial else self._artifact_for_report(workflow_run_id, report.id)
            findings = self._finding_repository.list_for_project(
                project_id,
                workflow_run_id=artifact_run_id,
            )
            insights = self._insight_repository.list_for_project(
                project_id,
                workflow_run_id=artifact_run_id,
            )
            evidence_items = self._evidence_repository.list_for_project(
                project_id,
                workflow_run_id=artifact_run_id,
            )
            evidence_items = qualifying_evidence(
                design=design, evidence=evidence_items, brief=brief,
                source_repository=self._report_service._source_repository,
            )
            # Run/design isolation: drop any foreign records that leaked into lists.
            findings = [
                item
                for item in findings
                if item.workflow_run_id == artifact_run_id
                and item.research_design_id == design.id
                and item.project_id == project_id
            ]
            insights = [
                item
                for item in insights
                if item.workflow_run_id == artifact_run_id
                and item.research_design_id == design.id
                and item.project_id == project_id
            ]
            evidence_items = [
                item
                for item in evidence_items
                if item.workflow_run_id == artifact_run_id
                and item.research_design_id == design.id
                and item.project_id == project_id
            ]
            structured = report.metadata.get("structured_claim_contract") == "desk_report_claim_v1"
            report_claims = tuple(
                self._report_claim_repository.list_for_report(report.id, report.revision_number)
            ) if structured and self._report_claim_repository is not None else ()
            if editorial:
                authority_issues = review_structured_claim_contract(
                    report=report, claims=report_claims, design=design,
                    findings=findings, insights=insights, evidence_items=evidence_items,
                    source_workflow_run_id=artifact_run_id,
                    coverage_contract=coverage_contract,
                )
                if authority_issues:
                    self._set_review_diagnostics(
                        context, phase="presentation_authority", status="failed",
                        category="deterministic_precheck_rejection",
                        rejection_codes=tuple(
                            str(item.metadata.get("code", "authority_invalid"))
                            for item in authority_issues[:16]
                        ),
                    )
                    raise ReviewError("Editorial Report factual authority is invalid")
                try:
                    presentation_input = build_presentation_review_input(
                        report=report, claims=report_claims,
                        coverage_contract=coverage_contract,
                    )
                except (PresentationPersistenceError, PresentationReviewError, ValueError) as exc:
                    self._set_review_diagnostics(
                        context, phase="presentation_precheck", status="failed",
                        category="deterministic_precheck_rejection",
                        rejection_codes=(str(exc)[:128],),
                    )
                    raise ReviewError("Invalid persisted editorial presentation") from exc

                deterministic_candidates = deterministic_presentation_issues(presentation_input)
                semantic_candidates = ()
                semantic_calls = 0
                if not deterministic_candidates:
                    semantic_candidates = self._run_presentation_semantic_review(
                        context=context, review_input=presentation_input,
                    )
                    semantic_calls = self._presentation_semantic_call_count()
                revision_calls = int(
                    report.metadata.get("editorial", {}).get("diagnostics", {}).get(
                        "provider_call_count", 0,
                    )
                ) if report.revision_number > 1 else 0
                initial_editorial_calls = int(
                    report.metadata.get("editorial_lifecycle", {}).get(
                        "initial_editorial_calls",
                        report.metadata.get("editorial", {}).get("diagnostics", {}).get(
                            "provider_call_count", 0,
                        ) if report.revision_number == 1 else 2,
                    )
                )
                prior_review_calls = int(report.metadata.get("editorial_lifecycle", {}).get("semantic_review_calls", 0))
                lifecycle_calls = 2 + initial_editorial_calls + prior_review_calls + revision_calls + semantic_calls
                if lifecycle_calls > MAX_FULL_REPORT_LIFECYCLE_CALLS:
                    raise ReviewError("Editorial lifecycle provider-call budget exhausted")
                all_issues = deduplicate_and_cluster_review_issues(
                    candidates_to_issues(tuple(deterministic_candidates) + tuple(semantic_candidates)),
                )
                dimensions = compute_quality_dimensions(all_issues)
                verdict = compute_verdict(all_issues)
                review_metadata = {
                    "report_revision": report.revision_number,
                    "structured_claim_contract": "desk_report_claim_v1",
                    "report_contract_version": EDITORIAL_CONTRACT_VERSION,
                    "reviewed_report_id": report.id,
                    "reviewed_revision_number": report.revision_number,
                    "authority_digest": presentation_input.authority_digest,
                    "presentation_digest": presentation_input.presentation_digest,
                    "claim_set_digest": claim_set_digest(report_claims),
                    "coverage_contract_digest": coverage_contract_digest(report),
                    "semantic_provider_call_count": semantic_calls,
                    "deterministic_issue_codes": sorted({
                        str(item.metadata.get("code", "")) for item in deterministic_candidates
                        if item.metadata.get("code")
                    })[:32],
                    "deterministic_review_summary": {
                        "issue_count": len(deterministic_candidates),
                        "passed": not deterministic_candidates,
                    },
                    "semantic_issue_ids": [
                        item.id for item in all_issues
                        if not item.metadata.get("deterministic")
                    ][:64],
                    "issue_targets": [
                        {
                            "target_type": str(item.metadata.get("target_type", ""))[:32],
                            "target_ref": str(item.metadata.get("target_ref", ""))[:128],
                        }
                        for item in (*deterministic_candidates, *semantic_candidates)
                    ][:64],
                    "revision_requested": verdict == ReviewVerdict.REVISE,
                    "revision_calls": revision_calls,
                    "lifecycle_provider_call_count": lifecycle_calls,
                    "final_verdict": verdict.value,
                }
                if verdict == ReviewVerdict.APPROVE:
                    review_metadata.update({
                        "approved_report_id": report.id,
                        "approved_revision_number": report.revision_number,
                        "approved_authority_digest": presentation_input.authority_digest,
                        "approved_presentation_digest": presentation_input.presentation_digest,
                    })
                review_id = self._persist_editorial_review(
                    project_id=project_id, workflow_run_id=workflow_run_id,
                    design_id=design.id, report=report, review_attempt=review_attempt,
                    verdict=verdict, dimensions=dimensions, issues=all_issues,
                    metadata=review_metadata,
                )
                if verdict == ReviewVerdict.APPROVE:
                    self._set_review_diagnostics(context, phase="review", status="completed")
                    return ReviewSummary(
                        review_id=review_id, verdict=verdict.value, report_id=report.id,
                        artifact_id=None, review_attempt=review_attempt,
                        revision_count=revision_count, issue_count=len(all_issues),
                    )
                if verdict == ReviewVerdict.REJECT or revision_count >= 1:
                    self._set_review_diagnostics(
                        context, phase="review", status="failed",
                        category="semantic_review_rejection",
                    )
                    raise ReviewError("Editorial Report did not receive exact approval")
                stored_review = self._review_repository.get_by_id(review_id)
                if stored_review is None:
                    raise ReviewError("Editorial Review record missing after persist")
                self._report_service.revise_for_context(context, review_result=stored_review)
                revision_count += 1
                continue
            claim_issues = review_structured_claim_contract(
                report=report, claims=report_claims, design=design,
                findings=findings, insights=insights, evidence_items=evidence_items,
                source_workflow_run_id=artifact_run_id,
                coverage_contract=coverage_contract,
            ) if structured else ()

            support_context = build_review_support_context(
                report=report,
                findings=findings,
                insights=insights,
                evidence_items=evidence_items,
                max_support_chars_per_section=None,
                citation_registry=report.citation_registry,
                authority_workflow_run_id=artifact_run_id,
            )
            support_issues = support_reference_issues(support_context)
            self._last_support_diagnostics = dict(support_context.diagnostics)

            pre_review_issues = run_deterministic_pre_review(
                report=report,
                design=design,
                findings=findings,
                insights=insights,
                coverage_contract=coverage_contract,
                report_claims=report_claims,
            )

            structural_issues = run_structural_review(
                report=report,
                brief=brief,
                design=design,
                findings=findings,
                artifact=artifact,
                coverage_contract=coverage_contract,
                report_claims=report_claims,
            )

            semantic_candidates = self._run_semantic_review(
                context=context,
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                design_id=design.id,
                report=report,
                brief_objectives=brief.objectives,
                research_questions=required_research_question_texts(
                    design=design, contract=coverage_contract,
                ),
                structural_issues=structural_issues,
                support_context=support_context,
                coverage_contract=coverage_contract,
                report_claims=report_claims,
            )
            if structured:
                semantic_candidates = self._target_structured_semantic_issues(
                    semantic_candidates, report=report, report_claims=report_claims,
                )
            coverage_issues = self._incomplete_coverage_issues()
            all_issues = deduplicate_and_cluster_review_issues(
                pre_review_issues
                + claim_issues
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
                    metadata={
                        "report_revision": report.revision_number,
                        "structured_claim_contract": ("desk_report_claim_v1" if structured else "legacy_unstructured"),
                        **({"claim_set_digest": claim_set_digest(report_claims),
                            "coverage_contract_digest": coverage_contract_digest(report)}
                           if structured else {}),
                    },
                ),
                workflow_run_id=workflow_run_id,
            )

            if verdict == ReviewVerdict.APPROVE:
                approved_artifact_id = self._approve_artifact(report, artifact)
                self._set_review_diagnostics(context, phase="review", status="completed")
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
                self._set_review_diagnostics(
                    context, phase="review", status="failed", category="semantic_review_rejection"
                )
                raise ReviewError(
                    f"Report rejected by quality gate for run {workflow_run_id}",
                )

            max_revisions = min(self._max_revision_attempts, 1) if structured else self._max_revision_attempts
            if revision_count >= max_revisions:
                self._reject_artifact(artifact)
                self._set_review_diagnostics(
                    context, phase="review", status="failed", category="semantic_review_rejection"
                )
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
        context: WorkflowContext,
        project_id: str,
        workflow_run_id: str,
        design_id: str,
        report: Report,
        brief_objectives: tuple[str, ...],
        research_questions: tuple[str, ...],
        structural_issues: tuple,
        support_context,
        coverage_contract,
        report_claims=(),
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
            report_mode=coverage_contract.mode,
            required_research_question_ids=coverage_contract.required_rq_ids,
            excluded_research_question_ids=coverage_contract.excluded_rq_ids,
            report_claim_ids=tuple(item.claim_id for item in report_claims),
            summary_units=tuple(item for item in report.metadata.get("summary_units", []) if isinstance(item, dict)),
        )
        try:
            return self._semantic_review_engine.review_report(review_input)
        except BudgetExhaustedError as exc:
            self._set_review_diagnostics(context, phase="semantic_review", status="failed", category="budget_exhausted")
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
            self._set_review_diagnostics(context, phase="semantic_review", status="failed", category="semantic_parse_failure")
            raise ReviewError(
                format_review_parse_failure_message(diagnostics),
            ) from exc

    def _run_presentation_semantic_review(self, *, context, review_input):
        reviewer = getattr(self._semantic_review_engine, "review_presentation", None)
        if not callable(reviewer):
            raise ReviewError("Semantic Review engine does not support desk_editorial_v1")
        try:
            return reviewer(review_input)
        except BudgetExhaustedError as exc:
            self._set_review_diagnostics(context, phase="semantic_review", status="failed", category="budget_exhausted")
            raise ReviewError(str(exc)) from exc
        except (ReviewConfigurationError, PresentationReviewError) as exc:
            self._set_review_diagnostics(context, phase="semantic_review", status="failed", category="semantic_parse_failure")
            raise ReviewError("Editorial semantic Review failed") from exc

    def _presentation_semantic_call_count(self) -> int:
        value = int(getattr(self._semantic_review_engine, "llm_call_count", 0))
        if value < 0 or value > 2:
            raise ReviewError("Editorial semantic Review call bound exceeded")
        return value

    def _persist_editorial_review(
        self, *, project_id, workflow_run_id, design_id, report, review_attempt,
        verdict, dimensions, issues, metadata,
    ) -> str:
        return self._persist_review(
            ReviewResult(
                id=str(uuid4()), project_id=project_id,
                workflow_run_id=workflow_run_id, research_design_id=design_id,
                report_id=report.id, artifact_id=None,
                previous_report_id=report.previous_report_id,
                review_attempt=review_attempt, verdict=verdict,
                quality_dimensions=dimensions, issues=issues,
                summary=self._build_summary(verdict, issues),
                review_method=self._semantic_review_engine.method_name,
                created_at=datetime.now(timezone.utc).isoformat(),
                deduplication_key=compute_review_deduplication_key(
                    workflow_run_id=workflow_run_id, report_id=report.id,
                    review_attempt=review_attempt,
                ),
                metadata=metadata,
            ),
            workflow_run_id=workflow_run_id,
        )

    @staticmethod
    def _target_structured_semantic_issues(candidates, *, report: Report, report_claims):
        claims = {item.claim_id for item in report_claims}
        sections = {item.id: item for item in report.sections}
        summary_units = [item for item in report.metadata.get("summary_units", []) if isinstance(item, dict)]
        targeted = []
        for candidate in candidates:
            section = sections.get(candidate.report_section_id or "")
            summary_indices = candidate.metadata.get("summary_unit_indices", []) if isinstance(candidate.metadata, dict) else []
            valid_summary = isinstance(summary_indices, list) and bool(summary_indices) and all(isinstance(index, int) and 0 <= index < len(summary_units) for index in summary_indices)
            summary_claims = tuple(dict.fromkeys(str(claim_id) for index in summary_indices for claim_id in summary_units[index].get("claim_ids", []))) if valid_summary else ()
            claim_refs = candidate.claim_refs or (section.claim_refs if section is not None else summary_claims)
            rq_refs = candidate.research_question_refs or (section.research_question_refs if section is not None else ())
            valid = (
                candidate.report_revision in {None, report.revision_number}
                and bool(section is not None or valid_summary or claim_refs or rq_refs)
                and set(claim_refs) <= claims
            )
            if not valid:
                targeted.append(
                    ReviewIssueCandidate(
                        issue_type="brief_mismatch", severity="major",
                        message="Semantic Review issue target is invalid for the exact Report revision",
                        report_revision=report.revision_number,
                        metadata={"code": "semantic_issue_target_invalid", "non_repairable": True},
                    )
                )
                continue
            targeted.append(replace(candidate, claim_refs=tuple(claim_refs), research_question_refs=tuple(rq_refs), report_revision=report.revision_number))
        return tuple(targeted)

    @staticmethod
    def _set_review_diagnostics(
        context: WorkflowContext,
        *,
        phase: str,
        status: str,
        category: str | None = None,
        rejection_codes: tuple[str, ...] = (),
    ) -> None:
        value: dict[str, Any] = {
            "version": 1,
            "phase": phase,
            "status": status,
            "workflow_run_id": context.workflow_run.id,
        }
        if category is not None:
            value["category"] = category
        if rejection_codes:
            value["rejection_codes"] = list(rejection_codes[:16])
        context.write_shared("review_diagnostics", value)

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

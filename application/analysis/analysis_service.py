from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType
from domain.findings.insight import Insight
from domain.research_brief import ResearchBrief
from domain.planning.research_design import ResearchDesign

from application.analysis.deduplication import (
    compute_finding_deduplication_key,
    compute_insight_deduplication_key,
)
from application.analysis.diagnostics import (
    FAILURE_CATEGORY_BATCH_ERROR,
    FAILURE_CATEGORY_LLM_ERROR,
    FAILURE_CATEGORY_PARSE_ERROR,
    AnalysisBatchDiagnostics,
    AnalysisFailureDiagnostics,
    classify_provenance_rejection,
    format_zero_findings_message,
)
from application.analysis.evidence_batching import batch_evidence_by_question
from application.analysis.exceptions import (
    AnalysisConfigurationError,
    AnalysisError,
    DuplicateFindingError,
    DuplicateInsightError,
    InvalidAnalysisProvenanceError,
)
from application.analysis.provenance_validation import (
    validate_finding_candidate,
    validate_insight_candidate,
)
from application.ports.analysis_ports import (
    AnalysisEngine,
    AnalysisInput,
    FindingRepository,
    InsightRepository,
)
from application.ports.evidence_ports import EvidenceRepository

from runtime.workflow_context import WorkflowContext

logger = logging.getLogger("ai_research_os.analysis")

_MAX_DEDUP_RETRIES = 5


@dataclass(frozen=True)
class AnalysisSummary:
    finding_ids: tuple[str, ...]
    insight_ids: tuple[str, ...]
    evidence_batches_processed: int
    finding_candidates_rejected: int
    insight_candidates_rejected: int
    batch_failures: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_ids": list(self.finding_ids),
            "insight_ids": list(self.insight_ids),
            "evidence_batches_processed": self.evidence_batches_processed,
            "finding_candidates_rejected": self.finding_candidates_rejected,
            "insight_candidates_rejected": self.insight_candidates_rejected,
            "batch_failures": self.batch_failures,
        }


class AnalysisService:
    """Transform run-scoped Evidence into validated Findings and Insights."""

    def __init__(
        self,
        *,
        analysis_engine: AnalysisEngine,
        evidence_repository: EvidenceRepository,
        finding_repository: FindingRepository,
        insight_repository: InsightRepository,
        max_evidence_per_batch: int,
        max_chars_per_batch: int,
    ) -> None:
        self._analysis_engine = analysis_engine
        self._evidence_repository = evidence_repository
        self._finding_repository = finding_repository
        self._insight_repository = insight_repository
        self._max_evidence_per_batch = max_evidence_per_batch
        self._max_chars_per_batch = max_chars_per_batch

    def analyze_for_context(self, context: WorkflowContext) -> AnalysisSummary:
        design = self._resolve_design(context)
        brief = self._resolve_brief(context)
        project_id = context.project.id
        workflow_run_id = context.workflow_run.id
        research_design_id = design.id

        evidence_items = self._evidence_repository.list_for_project(
            project_id,
            workflow_run_id=workflow_run_id,
        )
        if not evidence_items:
            raise AnalysisError(
                f"No run-scoped evidence available for analysis in run {workflow_run_id}",
            )

        evidence_by_id = {item.id: item for item in evidence_items}
        batches = batch_evidence_by_question(
            evidence_items,
            max_evidence_per_batch=self._max_evidence_per_batch,
            max_chars_per_batch=self._max_chars_per_batch,
        )

        finding_ids: list[str] = []
        finding_candidates_rejected = 0
        batch_failures = 0
        batch_diagnostics: list[AnalysisBatchDiagnostics] = []

        for batch_question_id, evidence_batch in batches:
            normalized_question_id = (
                None if batch_question_id == "__unscoped__" else batch_question_id
            )
            batch_diag = AnalysisBatchDiagnostics(
                batch_question_id=normalized_question_id,
                evidence_count=len(evidence_batch),
            )
            analysis_input = AnalysisInput(
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                research_design_id=research_design_id,
                brief=brief,
                design=design,
                evidence_batch=evidence_batch,
                batch_question_id=normalized_question_id,
            )
            try:
                candidates = self._analysis_engine.analyze_findings(analysis_input)
            except AnalysisConfigurationError as exc:
                batch_failures += 1
                batch_diag.failure_category = FAILURE_CATEGORY_LLM_ERROR
                logger.warning(
                    "analysis_batch_failed workflow_run_id=%s batch_question_id=%s "
                    "evidence_count=%s failure_category=%s error=%s",
                    workflow_run_id,
                    normalized_question_id,
                    len(evidence_batch),
                    batch_diag.failure_category,
                    type(exc).__name__,
                )
                batch_diagnostics.append(batch_diag)
                continue
            except ValueError as exc:
                batch_failures += 1
                batch_diag.failure_category = FAILURE_CATEGORY_PARSE_ERROR
                logger.warning(
                    "analysis_batch_failed workflow_run_id=%s batch_question_id=%s "
                    "evidence_count=%s failure_category=%s error=%s",
                    workflow_run_id,
                    normalized_question_id,
                    len(evidence_batch),
                    batch_diag.failure_category,
                    str(exc),
                )
                batch_diagnostics.append(batch_diag)
                continue
            except Exception as exc:
                batch_failures += 1
                batch_diag.failure_category = FAILURE_CATEGORY_BATCH_ERROR
                logger.exception(
                    "analysis_batch_failed workflow_run_id=%s batch_question_id=%s "
                    "evidence_count=%s failure_category=%s",
                    workflow_run_id,
                    normalized_question_id,
                    len(evidence_batch),
                    batch_diag.failure_category,
                )
                batch_diagnostics.append(batch_diag)
                continue

            engine_stats = getattr(
                self._analysis_engine,
                "last_finding_batch_stats",
                None,
            )
            if engine_stats is not None:
                batch_diag.candidate_count = engine_stats.candidate_count
                batch_diag.engine_dropped_count = engine_stats.engine_dropped_count
            else:
                batch_diag.candidate_count = len(candidates)

            for candidate in candidates:
                try:
                    validated = validate_finding_candidate(
                        candidate,
                        evidence_by_id=evidence_by_id,
                        project_id=project_id,
                        workflow_run_id=workflow_run_id,
                        research_design_id=research_design_id,
                        design=design,
                    )
                    finding_id = self._persist_finding(
                        candidate=validated,
                        project_id=project_id,
                        workflow_run_id=workflow_run_id,
                        research_design_id=research_design_id,
                    )
                except InvalidAnalysisProvenanceError as exc:
                    finding_candidates_rejected += 1
                    batch_diag.rejected_count += 1
                    category = classify_provenance_rejection(exc)
                    batch_diag.rejection_counts[category] = (
                        batch_diag.rejection_counts.get(category, 0) + 1
                    )
                    continue
                batch_diag.valid_count += 1
                if finding_id not in finding_ids:
                    finding_ids.append(finding_id)

            logger.info(
                "analysis_batch_complete workflow_run_id=%s batch_question_id=%s "
                "evidence_count=%s candidate_count=%s valid_count=%s rejected_count=%s "
                "engine_dropped_count=%s failure_category=%s rejection_counts=%s",
                workflow_run_id,
                normalized_question_id,
                batch_diag.evidence_count,
                batch_diag.candidate_count,
                batch_diag.valid_count,
                batch_diag.rejected_count,
                batch_diag.engine_dropped_count,
                batch_diag.failure_category,
                batch_diag.rejection_counts,
            )
            batch_diagnostics.append(batch_diag)

        if not finding_ids:
            failure_diagnostics = AnalysisFailureDiagnostics(
                workflow_run_id=workflow_run_id,
                evidence_count=len(evidence_items),
                batch_count=len(batches),
                batch_failures=batch_failures,
                finding_candidates_rejected=finding_candidates_rejected,
                batches=batch_diagnostics,
            )
            logger.error(
                "analysis_zero_findings %s",
                format_zero_findings_message(failure_diagnostics),
            )
            raise AnalysisError(format_zero_findings_message(failure_diagnostics))

        persisted_findings = [
            self._finding_repository.get_by_id(finding_id)
            for finding_id in finding_ids
        ]
        findings = [item for item in persisted_findings if item is not None]
        findings_by_id = {item.id: item for item in findings}

        insight_input = AnalysisInput(
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            research_design_id=research_design_id,
            brief=brief,
            design=design,
            evidence_batch=tuple(evidence_items),
            persisted_findings=tuple(findings),
        )

        insight_ids: list[str] = []
        insight_candidates_rejected = 0
        try:
            insight_candidates = self._analysis_engine.analyze_insights(insight_input)
        except Exception as exc:
            raise AnalysisError(
                f"Insight generation failed for workflow run {workflow_run_id}",
            ) from exc

        for candidate in insight_candidates:
            try:
                validated = validate_insight_candidate(
                    candidate,
                    findings_by_id=findings_by_id,
                    project_id=project_id,
                    workflow_run_id=workflow_run_id,
                    research_design_id=research_design_id,
                    design=design,
                )
                insight_id = self._persist_insight(
                    candidate=validated,
                    project_id=project_id,
                    workflow_run_id=workflow_run_id,
                    research_design_id=research_design_id,
                )
            except InvalidAnalysisProvenanceError:
                insight_candidates_rejected += 1
                continue
            if insight_id not in insight_ids:
                insight_ids.append(insight_id)

        if not insight_ids:
            raise AnalysisError(
                f"No valid insights produced for workflow run {workflow_run_id}",
            )

        return AnalysisSummary(
            finding_ids=tuple(finding_ids),
            insight_ids=tuple(insight_ids),
            evidence_batches_processed=len(batches),
            finding_candidates_rejected=finding_candidates_rejected,
            insight_candidates_rejected=insight_candidates_rejected,
            batch_failures=batch_failures,
        )

    def _resolve_design(self, context: WorkflowContext) -> ResearchDesign:
        template = context.workflow_template
        if template is None or template.research_design_snapshot is None:
            raise AnalysisError("Workflow template is missing research_design_snapshot")
        return template.research_design_snapshot

    def _resolve_brief(self, context: WorkflowContext) -> ResearchBrief:
        template = context.workflow_template
        if template is None or template.research_brief_snapshot is None:
            raise AnalysisError("Workflow template is missing research_brief_snapshot")
        return template.research_brief_snapshot

    def _persist_finding(
        self,
        *,
        candidate,
        project_id: str,
        workflow_run_id: str,
        research_design_id: str,
    ) -> str:
        deduplication_key = compute_finding_deduplication_key(
            workflow_run_id=workflow_run_id,
            statement=candidate.statement,
            evidence_refs=candidate.evidence_refs,
        )
        existing = self._finding_repository.get_by_deduplication_key(
            workflow_run_id,
            deduplication_key,
        )
        if existing is not None:
            return existing.id

        finding_type = candidate.finding_type
        if finding_type not in {member.value for member in FindingType}:
            finding_type = FindingType.SYNTHESIS.value

        finding = Finding(
            id=str(uuid4()),
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            research_design_id=research_design_id,
            research_question_refs=candidate.research_question_refs,
            information_need_refs=candidate.information_need_refs,
            statement=candidate.statement,
            rationale=candidate.rationale,
            evidence_refs=candidate.evidence_refs,
            finding_type=FindingType(finding_type),
            confidence=candidate.confidence,
            analysis_method=getattr(self._analysis_engine, "method_name", "unknown"),
            deduplication_key=deduplication_key,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata=dict(candidate.metadata or {}),
        )

        for _ in range(_MAX_DEDUP_RETRIES):
            try:
                self._finding_repository.create(finding)
                return finding.id
            except DuplicateFindingError:
                existing = self._finding_repository.get_by_deduplication_key(
                    workflow_run_id,
                    deduplication_key,
                )
                if existing is not None:
                    return existing.id

        raise AnalysisError(
            f"Failed to resolve concurrent finding persistence for run {workflow_run_id}",
        )

    def _persist_insight(
        self,
        *,
        candidate,
        project_id: str,
        workflow_run_id: str,
        research_design_id: str,
    ) -> str:
        deduplication_key = compute_insight_deduplication_key(
            workflow_run_id=workflow_run_id,
            statement=candidate.statement,
            finding_refs=candidate.finding_refs,
        )
        existing = self._insight_repository.get_by_deduplication_key(
            workflow_run_id,
            deduplication_key,
        )
        if existing is not None:
            return existing.id

        insight = Insight(
            id=str(uuid4()),
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            research_design_id=research_design_id,
            research_question_refs=candidate.research_question_refs,
            statement=candidate.statement,
            implication=candidate.implication,
            finding_refs=candidate.finding_refs,
            confidence=candidate.confidence,
            deduplication_key=deduplication_key,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata=dict(candidate.metadata or {}),
        )

        for _ in range(_MAX_DEDUP_RETRIES):
            try:
                self._insight_repository.create(insight)
                return insight.id
            except DuplicateInsightError:
                existing = self._insight_repository.get_by_deduplication_key(
                    workflow_run_id,
                    deduplication_key,
                )
                if existing is not None:
                    return existing.id

        raise AnalysisError(
            f"Failed to resolve concurrent insight persistence for run {workflow_run_id}",
        )

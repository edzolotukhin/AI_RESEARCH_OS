from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from domain.evidence.evidence import Evidence
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
    FindingEntailmentError,
    InvalidAnalysisProvenanceError,
)
from application.analysis.finding_entailment import (
    AcceptAllFindingEntailmentValidator,
    FindingEntailmentDiagnostics,
    FindingEntailmentStatus,
    FindingEntailmentValidator,
    ProvenanceValidFinding,
    batch_entailment_candidates,
    project_entailment_candidate,
    resolve_research_question_text,
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

from application.execution.exceptions import BudgetExhaustedError
from application.execution.budget_utils import is_budget_exhaustion
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
    entailment_diagnostics: FindingEntailmentDiagnostics | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "finding_ids": list(self.finding_ids),
            "insight_ids": list(self.insight_ids),
            "evidence_batches_processed": self.evidence_batches_processed,
            "finding_candidates_rejected": self.finding_candidates_rejected,
            "insight_candidates_rejected": self.insight_candidates_rejected,
            "batch_failures": self.batch_failures,
        }
        if self.entailment_diagnostics is not None:
            payload["entailment"] = self.entailment_diagnostics.to_dict()
        return payload


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
        finding_entailment_validator: FindingEntailmentValidator | None = None,
        max_entailment_candidates_per_batch: int | None = None,
        max_entailment_chars_per_batch: int | None = None,
    ) -> None:
        self._analysis_engine = analysis_engine
        self._evidence_repository = evidence_repository
        self._finding_repository = finding_repository
        self._insight_repository = insight_repository
        self._max_evidence_per_batch = max_evidence_per_batch
        self._max_chars_per_batch = max_chars_per_batch
        self._finding_entailment_validator = (
            finding_entailment_validator or AcceptAllFindingEntailmentValidator()
        )
        self._max_entailment_candidates_per_batch = max_entailment_candidates_per_batch
        self._max_entailment_chars_per_batch = max_entailment_chars_per_batch

    def analyze_for_context(self, context: WorkflowContext) -> AnalysisSummary:
        design = self._resolve_design(context)
        brief = self._resolve_brief(context)
        project_id = context.project.id
        workflow_run_id = context.workflow_run.id
        research_design_id = design.id
        questions_by_id = {question.id: question for question in design.research_questions}

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

        provenance_valid: list[ProvenanceValidFinding] = []
        finding_candidates_rejected = 0
        batch_failures = 0
        batch_diagnostics: list[AnalysisBatchDiagnostics] = []
        entailment_diagnostics = FindingEntailmentDiagnostics()
        next_candidate_index = 1

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
            except BudgetExhaustedError as exc:
                raise AnalysisError(str(exc)) from exc
            except AnalysisConfigurationError as exc:
                if is_budget_exhaustion(exc):
                    raise AnalysisError(str(exc)) from exc
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

            entailment_diagnostics.generated_candidate_count += len(candidates)

            for candidate in candidates:
                candidate_id = f"fc-{next_candidate_index:04d}"
                next_candidate_index += 1
                try:
                    validated = validate_finding_candidate(
                        candidate,
                        evidence_by_id=evidence_by_id,
                        project_id=project_id,
                        workflow_run_id=workflow_run_id,
                        research_design_id=research_design_id,
                        design=design,
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
                provenance_valid.append(
                    ProvenanceValidFinding(
                        candidate_id=candidate_id,
                        candidate=validated,
                        research_question_text=resolve_research_question_text(
                            validated,
                            questions_by_id=questions_by_id,
                        ),
                    ),
                )

            logger.info(
                "analysis_batch_complete workflow_run_id=%s batch_question_id=%s "
                "evidence_count=%s candidate_count=%s provenance_valid_count=%s "
                "rejected_count=%s engine_dropped_count=%s failure_category=%s "
                "rejection_counts=%s",
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

        entailment_diagnostics.provenance_valid_candidate_count = len(provenance_valid)

        if not provenance_valid:
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

        supported_candidates = self._run_entailment_gate(
            provenance_valid=provenance_valid,
            evidence_by_id=evidence_by_id,
            diagnostics=entailment_diagnostics,
            workflow_run_id=workflow_run_id,
        )

        finding_ids: list[str] = []
        for item in supported_candidates:
            finding_id = self._persist_finding(
                candidate=item.candidate,
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                research_design_id=research_design_id,
            )
            if finding_id not in finding_ids:
                finding_ids.append(finding_id)

        if not finding_ids:
            failure_diagnostics = AnalysisFailureDiagnostics(
                workflow_run_id=workflow_run_id,
                evidence_count=len(evidence_items),
                batch_count=len(batches),
                batch_failures=batch_failures,
                finding_candidates_rejected=(
                    finding_candidates_rejected
                    + entailment_diagnostics.entailment_submitted_count
                    - entailment_diagnostics.entailment_accepted_count
                ),
                batches=batch_diagnostics,
            )
            message = (
                f"{format_zero_findings_message(failure_diagnostics)}; "
                f"entailment={entailment_diagnostics.to_dict()}"
            )
            logger.error("analysis_zero_supported_findings %s", message)
            raise AnalysisError(message)

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
        except BudgetExhaustedError as exc:
            raise AnalysisError(str(exc)) from exc
        except AnalysisConfigurationError as exc:
            if is_budget_exhaustion(exc):
                raise AnalysisError(str(exc)) from exc
            raise AnalysisError(
                f"Insight generation failed for workflow run {workflow_run_id}",
            ) from exc
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
            finding_candidates_rejected=(
                finding_candidates_rejected
                + sum(entailment_diagnostics.rejected_by_status.values())
            ),
            insight_candidates_rejected=insight_candidates_rejected,
            batch_failures=batch_failures,
            entailment_diagnostics=entailment_diagnostics,
        )

    def _run_entailment_gate(
        self,
        *,
        provenance_valid: list[ProvenanceValidFinding],
        evidence_by_id: dict[str, Evidence],
        diagnostics: FindingEntailmentDiagnostics,
        workflow_run_id: str,
    ) -> list[ProvenanceValidFinding]:
        projections = [
            project_entailment_candidate(item, evidence_by_id=evidence_by_id)
            for item in provenance_valid
        ]
        batch_kwargs: dict[str, int] = {}
        if self._max_entailment_candidates_per_batch is not None:
            batch_kwargs["max_candidates_per_batch"] = (
                self._max_entailment_candidates_per_batch
            )
        if self._max_entailment_chars_per_batch is not None:
            batch_kwargs["max_chars_per_batch"] = self._max_entailment_chars_per_batch

        batches = batch_entailment_candidates(projections, **batch_kwargs)
        diagnostics.entailment_submitted_count = len(projections)

        verdicts_by_id: dict[str, FindingEntailmentStatus] = {}
        for batch in batches:
            try:
                verdicts = self._finding_entailment_validator.validate_batch(batch)
            except BudgetExhaustedError as exc:
                diagnostics.budget_stop_reason = str(exc)
                raise AnalysisError(
                    f"Finding entailment budget exhausted for workflow run "
                    f"{workflow_run_id}; no unvalidated Findings persisted; "
                    f"entailment={diagnostics.to_dict()}",
                ) from exc
            except FindingEntailmentError as exc:
                raise AnalysisError(
                    f"Finding entailment validation failed closed for workflow run "
                    f"{workflow_run_id}: {exc}; entailment={diagnostics.to_dict()}",
                ) from exc
            except AnalysisConfigurationError as exc:
                if is_budget_exhaustion(exc):
                    diagnostics.budget_stop_reason = str(exc)
                    raise AnalysisError(
                        f"Finding entailment budget exhausted for workflow run "
                        f"{workflow_run_id}; no unvalidated Findings persisted; "
                        f"entailment={diagnostics.to_dict()}",
                    ) from exc
                raise AnalysisError(
                    f"Finding entailment validation failed for workflow run "
                    f"{workflow_run_id}: {exc}; entailment={diagnostics.to_dict()}",
                ) from exc
            except Exception as exc:
                raise AnalysisError(
                    f"Finding entailment validation failed for workflow run "
                    f"{workflow_run_id}: {exc}; entailment={diagnostics.to_dict()}",
                ) from exc

            diagnostics.entailment_calls += 1
            if len(verdicts) != len(batch):
                raise AnalysisError(
                    f"Finding entailment returned unexpected verdict count for "
                    f"workflow run {workflow_run_id}; entailment={diagnostics.to_dict()}",
                )
            for projection, verdict in zip(batch, verdicts, strict=True):
                if verdict.candidate_id != projection.candidate_id:
                    raise AnalysisError(
                        f"Finding entailment verdict order mismatch for workflow run "
                        f"{workflow_run_id}; entailment={diagnostics.to_dict()}",
                    )
                if projection.candidate_id in verdicts_by_id:
                    raise AnalysisError(
                        f"Duplicate entailment coverage for {projection.candidate_id}",
                    )
                status = verdict.status
                if (
                    projection.truncated
                    and status == FindingEntailmentStatus.SUPPORTED
                ):
                    status = FindingEntailmentStatus.INSUFFICIENT_EVIDENCE
                verdicts_by_id[projection.candidate_id] = status

        if len(verdicts_by_id) != len(projections):
            raise AnalysisError(
                f"Incomplete entailment coverage for workflow run {workflow_run_id}; "
                f"entailment={diagnostics.to_dict()}",
            )

        supported: list[ProvenanceValidFinding] = []
        by_id = {item.candidate_id: item for item in provenance_valid}
        for item in provenance_valid:
            status = verdicts_by_id[item.candidate_id]
            if status == FindingEntailmentStatus.SUPPORTED:
                supported.append(item)
                diagnostics.entailment_accepted_count += 1
            else:
                diagnostics.record_rejection(item.candidate_id, status)
                logger.info(
                    "finding_entailment_rejected workflow_run_id=%s candidate_id=%s "
                    "status=%s statement=%s",
                    workflow_run_id,
                    item.candidate_id,
                    status.value,
                    item.candidate.statement[:160],
                )
        return supported

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

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.planning.research_design import ResearchDesign
from domain.sources.source import Source

from application.evidence.chunked_evidence_extractor import ChunkedEvidenceExtractor
from application.evidence.content_chunking import (
    DEFAULT_EVIDENCE_EXTRACTION_CHUNK_CHARS,
    DEFAULT_EVIDENCE_EXTRACTION_CHUNK_OVERLAP_CHARS,
)
from application.evidence.deduplication import compute_deduplication_key
from application.evidence.exceptions import (
    DuplicateEvidenceError,
    EvidenceExtractionError,
    UngroundedEvidenceError,
)
from application.evidence.grounding import verify_grounding
from application.evidence.provenance_validation import (
    InvalidProvenanceError,
    validate_candidate_provenance,
)
from application.evidence.evidence_extraction_scheduler import (
    EXTRACTION_ORDERING_COVERAGE_BEFORE_DEPTH,
    EvidenceExtractionWorkItem,
    PHASE_FIRST_OPPORTUNITY,
    build_need_fair_extraction_queue,
)
from application.evidence.evidence_extraction_diagnostics import (
    CandidateOutcome,
    CandidateRejectionReason,
    EvidenceExtractionDiagnostics,
    WorkItemTrace,
    activate_diagnostics,
    classify_grounding_failure,
    classify_provenance_rejection,
    deactivate_diagnostics,
    reset_active_work_item,
    set_active_work_item,
)
from application.evidence.run_scoped_provenance import resolve_run_scoped_context
from application.execution.budget_utils import (
    EVIDENCE_INITIAL_PARTITION_REASON,
    EVIDENCE_PURPOSE_INITIAL,
    EVIDENCE_PURPOSE_REMEDIATION,
    EVIDENCE_REMEDIATION_BUDGET_REASON,
    EVIDENCE_STAGE_CAP_REASON,
    is_evidence_graceful_budget_stop,
)
from application.execution.exceptions import BudgetExhaustedError
from application.execution.execution_budget_context import (
    get_evidence_call_purpose,
    get_execution_budget,
)
from application.execution.remediation_attempt_envelope import (
    EXTRACTION_BOUNDED_PARTIAL,
    EXTRACTION_FULLY_PROCESSED,
    RemediationAttemptEnvelope,
    RemediationAttemptEnvelopeReached,
    activate_remediation_attempt_envelope,
    build_remediation_attempt_envelope,
    remediations_reserved_remaining,
    reset_remediation_attempt_envelope,
)
from application.ports.evidence_ports import EvidenceExtractor, EvidenceRepository
from application.ports.source_ports import SourceRepository
from application.sources.provenance_merge import is_successful_acquisition

from runtime.workflow_context import WorkflowContext

_MAX_DEDUP_RETRIES = 5


@dataclass(frozen=True)
class EvidenceExtractionSummary:
    evidence_ids: tuple[str, ...]
    sources_processed: int
    evidence_extracted: int
    extraction_failures: int
    sources_without_evidence: int
    evidence_stage_budget_exhausted: bool = False
    budget_stop_reason: str | None = None
    diagnostics: EvidenceExtractionDiagnostics | None = None
    extraction_processing_state: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "evidence_ids": list(self.evidence_ids),
            "sources_processed": self.sources_processed,
            "evidence_extracted": self.evidence_extracted,
            "extraction_failures": self.extraction_failures,
            "sources_without_evidence": self.sources_without_evidence,
            "evidence_stage_budget_exhausted": self.evidence_stage_budget_exhausted,
        }
        if self.budget_stop_reason is not None:
            payload["budget_stop_reason"] = self.budget_stop_reason
        if self.extraction_processing_state is not None:
            payload["extraction_processing_state"] = self.extraction_processing_state
        if self.diagnostics is not None:
            payload["diagnostics"] = self.diagnostics.to_dict()
        return payload


class EvidenceExtractionService:
    """Extract grounded evidence from run-scoped acquired sources."""

    def __init__(
        self,
        *,
        evidence_extractor: EvidenceExtractor,
        evidence_repository: EvidenceRepository,
        source_repository: SourceRepository,
    ) -> None:
        self._evidence_extractor = evidence_extractor
        self._evidence_repository = evidence_repository
        self._source_repository = source_repository

    def extract_for_context(self, context: WorkflowContext) -> EvidenceExtractionSummary:
        design = self._resolve_design(context)
        project_id = context.project.id
        workflow_run_id = context.workflow_run.id
        all_sources = self._source_repository.list_for_project(
            project_id,
            workflow_run_id=workflow_run_id,
        )
        sources = self._eligible_sources(project_id, workflow_run_id)
        chunk_chars, overlap_chars = self._chunk_settings()

        diagnostics = EvidenceExtractionDiagnostics(workflow_run_id=workflow_run_id)
        diagnostics.sources_discovered = len(all_sources)
        diagnostics.sources_eligible = len(sources)
        diagnostics.sources_with_run_context = self._count_sources_with_run_context(
            sources,
            design=design,
            workflow_run_id=workflow_run_id,
            research_design_id=design.id,
        )
        diagnostics.information_needs_represented = self._represented_need_ids(
            sources,
            design=design,
            workflow_run_id=workflow_run_id,
            research_design_id=design.id,
        )

        queue = build_need_fair_extraction_queue(
            sources,
            design=design,
            workflow_run_id=workflow_run_id,
            research_design_id=design.id,
            chunk_chars=chunk_chars,
            overlap_chars=overlap_chars,
        )
        diagnostics.queue_items = len(queue)
        diagnostics.outer_chunks = len(queue)
        diagnostics.extraction_ordering = EXTRACTION_ORDERING_COVERAGE_BEFORE_DEPTH
        diagnostics.first_opportunity_work_items = sum(
            1 for item in queue if item.phase == PHASE_FIRST_OPPORTUNITY
        )
        diagnostics.depth_work_items = (
            diagnostics.queue_items - diagnostics.first_opportunity_work_items
        )
        diagnostics.first_opportunity_sources = diagnostics.first_opportunity_work_items

        token = activate_diagnostics(diagnostics)
        try:
            return self._extract_work_queue(
                queue,
                design=design,
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                research_design_id=design.id,
                allow_empty_failure=True,
                diagnostics=diagnostics,
            )
        finally:
            deactivate_diagnostics(token)

    def extract_for_source_ids(
        self,
        context: WorkflowContext,
        source_ids: tuple[str, ...],
        *,
        allow_empty: bool = False,
        attempt_max_llm_calls: int = 0,
    ) -> EvidenceExtractionSummary:
        """Extract evidence from specific run-scoped sources (targeted append)."""
        design = self._resolve_design(context)
        project_id = context.project.id
        workflow_run_id = context.workflow_run.id
        if not source_ids:
            return EvidenceExtractionSummary(
                evidence_ids=(),
                sources_processed=0,
                evidence_extracted=0,
                extraction_failures=0,
                sources_without_evidence=0,
                diagnostics=EvidenceExtractionDiagnostics(
                    workflow_run_id=workflow_run_id,
                ),
            )

        eligible = {
            source.id: source
            for source in self._eligible_sources(project_id, workflow_run_id)
        }
        selected_sources = [
            eligible[source_id]
            for source_id in source_ids
            if source_id in eligible
        ]
        chunk_chars, overlap_chars = self._chunk_settings()
        diagnostics = EvidenceExtractionDiagnostics(workflow_run_id=workflow_run_id)
        diagnostics.sources_discovered = len(
            self._source_repository.list_for_project(project_id, workflow_run_id=workflow_run_id),
        )
        diagnostics.sources_eligible = len(eligible)
        diagnostics.sources_with_run_context = self._count_sources_with_run_context(
            selected_sources,
            design=design,
            workflow_run_id=workflow_run_id,
            research_design_id=design.id,
        )
        diagnostics.information_needs_represented = self._represented_need_ids(
            selected_sources,
            design=design,
            workflow_run_id=workflow_run_id,
            research_design_id=design.id,
        )
        queue = build_need_fair_extraction_queue(
            selected_sources,
            design=design,
            workflow_run_id=workflow_run_id,
            research_design_id=design.id,
            chunk_chars=chunk_chars,
            overlap_chars=overlap_chars,
        )
        diagnostics.queue_items = len(queue)
        diagnostics.outer_chunks = len(queue)
        diagnostics.extraction_ordering = EXTRACTION_ORDERING_COVERAGE_BEFORE_DEPTH
        diagnostics.first_opportunity_work_items = sum(
            1 for item in queue if item.phase == PHASE_FIRST_OPPORTUNITY
        )
        diagnostics.depth_work_items = (
            diagnostics.queue_items - diagnostics.first_opportunity_work_items
        )
        diagnostics.first_opportunity_sources = diagnostics.first_opportunity_work_items

        token = activate_diagnostics(diagnostics)
        try:
            return self._extract_work_queue(
                queue,
                design=design,
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                research_design_id=design.id,
                allow_empty_failure=not allow_empty,
                diagnostics=diagnostics,
                attempt_max_llm_calls=attempt_max_llm_calls,
            )
        finally:
            deactivate_diagnostics(token)

    def _resolve_design(self, context: WorkflowContext) -> ResearchDesign:
        template = context.workflow_template
        if template is None or template.research_design_snapshot is None:
            raise EvidenceExtractionError(
                "Workflow template is missing research_design_snapshot",
            )
        return template.research_design_snapshot

    def _eligible_sources(self, project_id: str, workflow_run_id: str) -> list[Source]:
        sources = self._source_repository.list_for_project(
            project_id,
            workflow_run_id=workflow_run_id,
        )
        return [
            source
            for source in sources
            if is_successful_acquisition(source.retrieval_status)
            and source.content_text.strip()
        ]

    def _chunk_settings(self) -> tuple[int, int]:
        extractor = self._evidence_extractor
        if isinstance(extractor, ChunkedEvidenceExtractor):
            return extractor.chunk_chars, extractor.overlap_chars
        return (
            DEFAULT_EVIDENCE_EXTRACTION_CHUNK_CHARS,
            DEFAULT_EVIDENCE_EXTRACTION_CHUNK_OVERLAP_CHARS,
        )

    def _count_sources_with_run_context(
        self,
        sources: list[Source],
        *,
        design: ResearchDesign,
        workflow_run_id: str,
        research_design_id: str,
    ) -> int:
        count = 0
        for source in sources:
            context = resolve_run_scoped_context(
                source=source,
                design=design,
                workflow_run_id=workflow_run_id,
                research_design_id=research_design_id,
            )
            if context.information_need_ids:
                count += 1
        return count

    @staticmethod
    def _represented_need_ids(
        sources: list[Source],
        *,
        design: ResearchDesign,
        workflow_run_id: str,
        research_design_id: str,
    ) -> tuple[str, ...]:
        need_ids: set[str] = set()
        for source in sources:
            context = resolve_run_scoped_context(
                source=source,
                design=design,
                workflow_run_id=workflow_run_id,
                research_design_id=research_design_id,
            )
            need_ids.update(context.information_need_ids)
        return tuple(sorted(need_ids))

    def _extract_work_queue(
        self,
        queue: list[EvidenceExtractionWorkItem],
        *,
        design: ResearchDesign,
        project_id: str,
        workflow_run_id: str,
        research_design_id: str,
        allow_empty_failure: bool,
        diagnostics: EvidenceExtractionDiagnostics,
        attempt_max_llm_calls: int = 0,
    ) -> EvidenceExtractionSummary:
        evidence_ids: list[str] = []
        extracted = 0
        failures = 0
        sources_without_evidence: set[str] = set()
        sources_with_evidence: set[str] = set()
        sources_touched: set[str] = set()
        evidence_stage_budget_exhausted = False
        budget_stop_reason: str | None = None
        budget_stop_before_any_attempt = False
        envelope = None
        envelope_token = None
        purpose = get_evidence_call_purpose()
        if attempt_max_llm_calls > 0 and purpose == EVIDENCE_PURPOSE_REMEDIATION:
            envelope = build_remediation_attempt_envelope(
                configured_limit=attempt_max_llm_calls,
                budget=get_execution_budget(),
            )
            if envelope is not None:
                envelope_token = activate_remediation_attempt_envelope(envelope)
                diagnostics.remediation_attempt_configured_limit = (
                    envelope.configured_limit
                )
                diagnostics.remediation_attempt_effective_limit = (
                    envelope.effective_limit
                )
                diagnostics.remediation_calls_remaining_before = (
                    envelope.remediations_reserved_remaining_at_start
                )
        diagnostics.planned_work_items = len(queue)

        try:
            return self._run_extract_work_queue(
                queue,
                design=design,
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                research_design_id=research_design_id,
                allow_empty_failure=allow_empty_failure,
                diagnostics=diagnostics,
                envelope=envelope,
                evidence_ids=evidence_ids,
                extracted=extracted,
                failures=failures,
                sources_without_evidence=sources_without_evidence,
                sources_with_evidence=sources_with_evidence,
                sources_touched=sources_touched,
                evidence_stage_budget_exhausted=evidence_stage_budget_exhausted,
                budget_stop_reason=budget_stop_reason,
                budget_stop_before_any_attempt=budget_stop_before_any_attempt,
            )
        finally:
            if envelope_token is not None:
                reset_remediation_attempt_envelope(envelope_token)

    def _run_extract_work_queue(
        self,
        queue: list[EvidenceExtractionWorkItem],
        *,
        design: ResearchDesign,
        project_id: str,
        workflow_run_id: str,
        research_design_id: str,
        allow_empty_failure: bool,
        diagnostics: EvidenceExtractionDiagnostics,
        envelope: RemediationAttemptEnvelope | None,
        evidence_ids: list[str],
        extracted: int,
        failures: int,
        sources_without_evidence: set[str],
        sources_with_evidence: set[str],
        sources_touched: set[str],
        evidence_stage_budget_exhausted: bool,
        budget_stop_reason: str | None,
        budget_stop_before_any_attempt: bool,
    ) -> EvidenceExtractionSummary:
        for queue_index, work_item in enumerate(queue):
            budget = get_execution_budget()
            if envelope is not None and budget is not None and envelope.reached(budget):
                diagnostics.remediation_attempt_capped = True
                break
            stop_reason = self._next_evidence_budget_stop_reason()
            if stop_reason is not None:
                budget_stop_reason = stop_reason
                evidence_stage_budget_exhausted = stop_reason in {
                    EVIDENCE_STAGE_CAP_REASON,
                    EVIDENCE_INITIAL_PARTITION_REASON,
                    EVIDENCE_REMEDIATION_BUDGET_REASON,
                }
                budget_stop_before_any_attempt = diagnostics.extractor_attempts == 0
                diagnostics.budget_stop = True
                diagnostics.evidence_stage_cap_reached = evidence_stage_budget_exhausted
                diagnostics.budget_stop_reason = budget_stop_reason
                break

            source_id = work_item.source.id
            sources_touched.add(source_id)

            trace = WorkItemTrace(
                queue_index=queue_index,
                source_id=source_id,
                source_content_checksum=work_item.source.content_checksum or "",
                information_need_ids=work_item.run_context.information_need_ids,
                outer_chunk_index=work_item.chunk_index,
                outer_chunk_normalized_start=work_item.chunk.original_normalized_start,
                outer_chunk_normalized_end=work_item.chunk.original_normalized_end,
                outer_chunk_length=len(work_item.chunk.text),
                text_passed_to_extractor_length=len(work_item.chunk.text),
                phase=work_item.phase,
                source_first_attempt=work_item.source_first_attempt,
                primary_need_id=work_item.primary_need_id,
                chunk_index=work_item.chunk_index,
            )
            diagnostics.work_items.append(trace)
            work_item_token = set_active_work_item(trace)
            try:
                source_ids, source_extracted, source_failures, had_none = (
                    self._extract_work_item(
                        work_item=work_item,
                        design=design,
                        project_id=project_id,
                        workflow_run_id=workflow_run_id,
                        research_design_id=research_design_id,
                        diagnostics=diagnostics,
                        trace=trace,
                    )
                )
            except RemediationAttemptEnvelopeReached:
                diagnostics.remediation_attempt_capped = True
                reset_active_work_item(work_item_token)
                break
            except BudgetExhaustedError as exc:
                stop_reason = self._graceful_budget_stop_reason(exc)
                if stop_reason is None:
                    raise
                budget_stop_reason = stop_reason
                evidence_stage_budget_exhausted = stop_reason in {
                    EVIDENCE_STAGE_CAP_REASON,
                    EVIDENCE_INITIAL_PARTITION_REASON,
                    EVIDENCE_REMEDIATION_BUDGET_REASON,
                }
                diagnostics.budget_stop = True
                diagnostics.evidence_stage_cap_reached = evidence_stage_budget_exhausted
                diagnostics.budget_stop_reason = budget_stop_reason
                trace.extractor_status = "budget_stop"
                trace.exception_class = type(exc).__name__
                trace.exception_message = str(exc)
                diagnostics.record_exception(exc)
                break
            finally:
                reset_active_work_item(work_item_token)

            evidence_ids.extend(source_ids)
            extracted += source_extracted
            failures += source_failures
            if source_extracted > 0:
                sources_with_evidence.add(source_id)
            elif had_none:
                sources_without_evidence.add(source_id)

            stop_reason = self._post_source_budget_stop_reason()
            if stop_reason is not None:
                budget_stop_reason = stop_reason
                evidence_stage_budget_exhausted = stop_reason in {
                    EVIDENCE_STAGE_CAP_REASON,
                    EVIDENCE_INITIAL_PARTITION_REASON,
                    EVIDENCE_REMEDIATION_BUDGET_REASON,
                }
                diagnostics.budget_stop = True
                diagnostics.evidence_stage_cap_reached = evidence_stage_budget_exhausted
                diagnostics.budget_stop_reason = budget_stop_reason
                break

        sources_without_evidence -= sources_with_evidence
        diagnostics.persisted_evidence = extracted
        self._finalize_attempt_envelope_diagnostics(
            diagnostics,
            queue_len=len(queue),
            envelope=envelope,
        )
        diagnostics.classify(
            persisted_evidence=extracted,
            budget_stop_before_any_attempt=budget_stop_before_any_attempt,
        )

        if extracted == 0 and allow_empty_failure:
            summary = EvidenceExtractionSummary(
                evidence_ids=tuple(evidence_ids),
                sources_processed=len(sources_touched),
                evidence_extracted=extracted,
                extraction_failures=failures,
                sources_without_evidence=len(sources_without_evidence),
                evidence_stage_budget_exhausted=evidence_stage_budget_exhausted,
                budget_stop_reason=budget_stop_reason,
                diagnostics=diagnostics,
                extraction_processing_state=diagnostics.extraction_processing_state,
            )
            raise EvidenceExtractionError(
                f"No grounded evidence extracted for workflow run {workflow_run_id}",
                summary=summary,
            )

        return EvidenceExtractionSummary(
            evidence_ids=tuple(evidence_ids),
            sources_processed=len(sources_touched),
            evidence_extracted=extracted,
            extraction_failures=failures,
            sources_without_evidence=len(sources_without_evidence),
            evidence_stage_budget_exhausted=evidence_stage_budget_exhausted,
            budget_stop_reason=budget_stop_reason,
            diagnostics=diagnostics,
            extraction_processing_state=diagnostics.extraction_processing_state,
        )

    @staticmethod
    def _finalize_attempt_envelope_diagnostics(
        diagnostics: EvidenceExtractionDiagnostics,
        *,
        queue_len: int,
        envelope: RemediationAttemptEnvelope | None,
    ) -> None:
        processed = len(diagnostics.work_items)
        skipped = max(0, queue_len - processed)
        diagnostics.planned_work_items = queue_len
        diagnostics.processed_work_items = processed
        diagnostics.skipped_work_items = skipped
        budget = get_execution_budget()
        if envelope is not None and budget is not None:
            consumed = envelope.actual_evidence_calls_consumed(budget)
            diagnostics.remediation_attempt_calls_consumed = consumed
            diagnostics.remediation_calls_remaining_after = (
                remediations_reserved_remaining(budget)
            )
            if envelope.reached(budget):
                diagnostics.remediation_attempt_capped = True
            if skipped > 0 and diagnostics.remediation_attempt_capped:
                diagnostics.extraction_processing_state = EXTRACTION_BOUNDED_PARTIAL
            elif skipped == 0:
                diagnostics.extraction_processing_state = EXTRACTION_FULLY_PROCESSED
        elif skipped == 0:
            diagnostics.extraction_processing_state = EXTRACTION_FULLY_PROCESSED
        if diagnostics.extraction_processing_state:
            for trace in diagnostics.work_items:
                trace.source_processing_state = diagnostics.extraction_processing_state

    def _extract_work_item(
        self,
        *,
        work_item: EvidenceExtractionWorkItem,
        design: ResearchDesign,
        project_id: str,
        workflow_run_id: str,
        research_design_id: str,
        diagnostics: EvidenceExtractionDiagnostics,
        trace: WorkItemTrace,
    ) -> tuple[list[str], int, int, bool]:
        chunk_source = replace(
            work_item.source,
            content_text=work_item.chunk.text,
        )
        return self._extract_from_source(
            source=chunk_source,
            design=design,
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            research_design_id=research_design_id,
            run_context=work_item.run_context,
            chunk_metadata={
                "chunk_normalized_start": work_item.chunk.original_normalized_start,
                "chunk_normalized_end": work_item.chunk.original_normalized_end,
            },
            diagnostics=diagnostics,
            trace=trace,
        )

    def _extract_from_source(
        self,
        *,
        source: Source,
        design: ResearchDesign,
        project_id: str,
        workflow_run_id: str,
        research_design_id: str,
        run_context=None,
        chunk_metadata: dict | None = None,
        diagnostics: EvidenceExtractionDiagnostics | None = None,
        trace: WorkItemTrace | None = None,
    ) -> tuple[list[str], int, int, bool]:
        evidence_ids: list[str] = []
        extracted = 0
        failures = 0

        run_context = run_context or resolve_run_scoped_context(
            source=source,
            design=design,
            workflow_run_id=workflow_run_id,
            research_design_id=research_design_id,
        )
        if trace is not None:
            trace.text_passed_to_extractor_length = len(source.content_text)
            if chunk_metadata:
                trace.grounding_search_start = chunk_metadata.get("chunk_normalized_start")
                trace.grounding_search_end = chunk_metadata.get("chunk_normalized_end")

        if not run_context.information_need_ids:
            if trace is not None:
                trace.extractor_status = "no_run_context"
            if diagnostics is not None:
                diagnostics.extractor_attempts += 1
            return evidence_ids, extracted, failures, True

        if diagnostics is not None:
            diagnostics.extractor_attempts += 1
        if trace is not None:
            trace.extractor_attempts += 1

        try:
            candidates = self._evidence_extractor.extract(
                source=source,
                design=design,
                run_context=run_context,
            )
        except BudgetExhaustedError as exc:
            if is_evidence_graceful_budget_stop(exc):
                if trace is not None:
                    trace.extractor_status = "budget_stop"
                    trace.exception_class = type(exc).__name__
                    trace.exception_message = str(exc)
                if diagnostics is not None:
                    diagnostics.record_exception(exc)
                return evidence_ids, extracted, failures, extracted == 0
            raise
        except Exception as exc:
            if trace is not None:
                trace.extractor_status = "exception"
                trace.exception_class = type(exc).__name__
                trace.exception_message = str(exc)
            if diagnostics is not None:
                diagnostics.extractor_failures += 1
                diagnostics.record_exception(exc)
            return evidence_ids, extracted, failures + 1, True

        if trace is not None:
            trace.raw_candidate_count = len(candidates)
        if diagnostics is not None:
            diagnostics.raw_candidates += len(candidates)

        if not candidates:
            if trace is not None:
                trace.extractor_status = "no_candidates"
            return evidence_ids, extracted, failures, True

        if trace is not None:
            trace.extractor_status = "success"
        if diagnostics is not None:
            diagnostics.extractor_successes += 1

        for candidate_index, candidate in enumerate(candidates):
            if not candidate.statement.strip() or not candidate.source_excerpt.strip():
                failures += 1
                if diagnostics is not None:
                    diagnostics.rejected_empty_or_invalid_candidate += 1
                if trace is not None:
                    trace.candidate_outcomes.append(
                        CandidateOutcome(
                            candidate_index=candidate_index,
                            outcome="rejected",
                            rejection_reason=CandidateRejectionReason.EMPTY_OR_INVALID.value,
                            information_need_refs=candidate.information_need_refs,
                            excerpt_length=len(candidate.source_excerpt),
                            statement_length=len(candidate.statement),
                        ),
                    )
                continue

            try:
                validated = validate_candidate_provenance(
                    candidate,
                    run_context=run_context,
                    design=design,
                )
                merged_metadata = dict(validated.metadata or {})
                if chunk_metadata:
                    merged_metadata.update(chunk_metadata)
                validated = replace(validated, metadata=merged_metadata)
                evidence_id, dedup_hit = self._persist_candidate(
                    candidate=validated,
                    source=source,
                    project_id=project_id,
                    workflow_run_id=workflow_run_id,
                    research_design_id=research_design_id,
                )
            except InvalidProvenanceError as exc:
                failures += 1
                reason = classify_provenance_rejection(str(exc))
                if reason == CandidateRejectionReason.INVALID_NEED_REF.value:
                    if diagnostics is not None:
                        diagnostics.rejected_invalid_or_missing_need_ref += 1
                else:
                    if diagnostics is not None:
                        diagnostics.rejected_provenance += 1
                if trace is not None:
                    trace.candidate_outcomes.append(
                        CandidateOutcome(
                            candidate_index=candidate_index,
                            outcome="rejected",
                            rejection_reason=reason,
                            information_need_refs=candidate.information_need_refs,
                            excerpt_length=len(candidate.source_excerpt),
                            statement_length=len(candidate.statement),
                        ),
                    )
                continue
            except UngroundedEvidenceError:
                failures += 1
                chunk_start = (
                    int(chunk_metadata["chunk_normalized_start"])
                    if chunk_metadata and chunk_metadata.get("chunk_normalized_start") is not None
                    else None
                )
                chunk_end = (
                    int(chunk_metadata["chunk_normalized_end"])
                    if chunk_metadata and chunk_metadata.get("chunk_normalized_end") is not None
                    else None
                )
                grounding_detail = classify_grounding_failure(
                    source_text=source.content_text,
                    excerpt=candidate.source_excerpt,
                    chunk_normalized_start=chunk_start,
                    chunk_normalized_end=chunk_end,
                )
                if diagnostics is not None:
                    diagnostics.rejected_grounding += 1
                if trace is not None:
                    trace.candidate_outcomes.append(
                        CandidateOutcome(
                            candidate_index=candidate_index,
                            outcome="rejected",
                            rejection_reason=CandidateRejectionReason.GROUNDING.value,
                            grounding_detail=grounding_detail,
                            information_need_refs=candidate.information_need_refs,
                            excerpt_length=len(candidate.source_excerpt),
                            statement_length=len(candidate.statement),
                        ),
                    )
                continue

            if dedup_hit:
                if diagnostics is not None:
                    diagnostics.dedup_hits += 1
                if trace is not None:
                    trace.candidate_outcomes.append(
                        CandidateOutcome(
                            candidate_index=candidate_index,
                            outcome="dedup",
                            rejection_reason=CandidateRejectionReason.DEDUP.value,
                            information_need_refs=candidate.information_need_refs,
                            excerpt_length=len(candidate.source_excerpt),
                            statement_length=len(candidate.statement),
                        ),
                    )
            else:
                if trace is not None:
                    trace.candidate_outcomes.append(
                        CandidateOutcome(
                            candidate_index=candidate_index,
                            outcome="persisted",
                            rejection_reason=CandidateRejectionReason.PERSISTED.value,
                            information_need_refs=candidate.information_need_refs,
                            excerpt_length=len(candidate.source_excerpt),
                            statement_length=len(candidate.statement),
                        ),
                    )
            evidence_ids.append(evidence_id)
            extracted += 1

        return evidence_ids, extracted, failures, extracted == 0

    @staticmethod
    def _graceful_budget_stop_reason(exc: BudgetExhaustedError) -> str | None:
        if is_evidence_graceful_budget_stop(exc):
            return exc.reason
        return None

    @classmethod
    def _next_evidence_budget_stop_reason(cls) -> str | None:
        budget = get_execution_budget()
        if budget is None:
            return None
        purpose = get_evidence_call_purpose() or EVIDENCE_PURPOSE_INITIAL
        try:
            budget.assert_can_call("evidence", purpose=purpose)
        except BudgetExhaustedError as exc:
            reason = cls._graceful_budget_stop_reason(exc)
            if reason is not None:
                return reason
            raise
        return None

    @classmethod
    def _post_source_budget_stop_reason(cls) -> str | None:
        budget = get_execution_budget()
        purpose = get_evidence_call_purpose() or EVIDENCE_PURPOSE_INITIAL
        if budget is not None:
            if purpose == EVIDENCE_PURPOSE_REMEDIATION:
                if budget.evidence_total_cap_reached():
                    return (
                        EVIDENCE_REMEDIATION_BUDGET_REASON
                        if budget.evidence_remediation_reserved > 0
                        else EVIDENCE_STAGE_CAP_REASON
                    )
            elif budget.evidence_initial_partition_reached():
                return (
                    EVIDENCE_INITIAL_PARTITION_REASON
                    if budget.evidence_remediation_reserved > 0
                    else EVIDENCE_STAGE_CAP_REASON
                )
            elif budget.evidence_total_cap_reached():
                return EVIDENCE_STAGE_CAP_REASON
        return cls._next_evidence_budget_stop_reason()

    @staticmethod
    def _evidence_stage_cap_reached() -> bool:
        budget = get_execution_budget()
        if budget is None:
            return False
        return budget.stage_cap_reached("evidence")

    def _persist_candidate(
        self,
        *,
        candidate,
        source: Source,
        project_id: str,
        workflow_run_id: str,
        research_design_id: str,
    ) -> tuple[str, bool]:
        metadata = dict(candidate.metadata or {})
        chunk_start = metadata.get("chunk_normalized_start")
        chunk_end = metadata.get("chunk_normalized_end")
        checksum = source.content_checksum or ""
        locator = verify_grounding(
            source_text=source.content_text,
            excerpt=candidate.source_excerpt,
            chunk_normalized_start=(
                int(chunk_start) if chunk_start is not None else None
            ),
            chunk_normalized_end=int(chunk_end) if chunk_end is not None else None,
        )
        deduplication_key = compute_deduplication_key(
            source_id=source.id,
            source_content_checksum=checksum,
            statement=candidate.statement,
            source_excerpt=candidate.source_excerpt,
            information_need_refs=candidate.information_need_refs,
        )
        existing = self._evidence_repository.get_by_deduplication_key(
            workflow_run_id,
            deduplication_key,
        )
        if existing is not None:
            return existing.id, True

        evidence = Evidence(
            id=str(uuid4()),
            project_id=project_id,
            source_id=source.id,
            source_content_checksum=checksum,
            workflow_run_id=workflow_run_id,
            research_design_id=research_design_id,
            research_question_refs=candidate.research_question_refs,
            information_need_refs=candidate.information_need_refs,
            evidence_type=EvidenceType(candidate.evidence_type),
            statement=candidate.statement,
            source_excerpt=candidate.source_excerpt,
            source_locator=locator.to_dict(),
            extraction_method=getattr(self._evidence_extractor, "method_name", "unknown"),
            confidence=candidate.confidence,
            quality_signals={
                "direct": candidate.direct,
                "source_retrieval_status": source.retrieval_status.value,
                "source_type": source.source_type,
            },
            deduplication_key=deduplication_key,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata=metadata,
        )

        for _ in range(_MAX_DEDUP_RETRIES):
            try:
                self._evidence_repository.create(evidence)
                return evidence.id, False
            except DuplicateEvidenceError:
                existing = self._evidence_repository.get_by_deduplication_key(
                    workflow_run_id,
                    deduplication_key,
                )
                if existing is not None:
                    return existing.id, True

        raise EvidenceExtractionError(
            f"Failed to resolve concurrent evidence persistence for run "
            f"{workflow_run_id}",
        )

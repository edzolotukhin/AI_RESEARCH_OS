from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from application.evidence.evidence_extractor_response_shape import ResponseShapeDiagnostics
from application.evidence.grounding import locate_excerpt, normalize_source_text


class EvidenceStageFailureClassification(str, Enum):
    """Diagnostic-only taxonomy for a zero-evidence or partial evidence stage."""

    NO_ELIGIBLE_SOURCES = "no_eligible_sources"
    NO_RUN_SCOPED_CONTEXT = "no_run_scoped_context"
    EMPTY_EXTRACTION_QUEUE = "empty_extraction_queue"
    EXTRACTOR_FAILURE = "extractor_failure"
    NO_CANDIDATES = "no_candidates"
    INVALID_NEED_REFS_ALL = "invalid_need_refs_all"
    PROVENANCE_REJECTED_ALL = "provenance_rejected_all"
    GROUNDING_REJECTED_ALL = "grounding_rejected_all"
    BUDGET_EXHAUSTED_BEFORE_EVIDENCE = "budget_exhausted_before_evidence"
    MIXED_FAILURE = "mixed_failure"
    SUCCESS = "success"


class CandidateRejectionReason(str, Enum):
    INVALID_NEED_REF = "invalid_need_ref"
    PROVENANCE = "provenance"
    GROUNDING = "grounding"
    EMPTY_OR_INVALID = "empty_or_invalid"
    DEDUP = "dedup"
    PERSISTED = "persisted"


@dataclass
class InnerChunkObservation:
    inner_chunk_index: int
    inner_chunk_normalized_start: int
    inner_chunk_normalized_end: int
    inner_chunk_length: int
    extractor_status: str
    exception_class: str | None = None
    exception_message: str | None = None
    raw_candidate_count: int = 0
    response_shape: ResponseShapeDiagnostics | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "inner_chunk_index": self.inner_chunk_index,
            "inner_chunk_normalized_start": self.inner_chunk_normalized_start,
            "inner_chunk_normalized_end": self.inner_chunk_normalized_end,
            "inner_chunk_length": self.inner_chunk_length,
            "extractor_status": self.extractor_status,
            "raw_candidate_count": self.raw_candidate_count,
        }
        if self.exception_class is not None:
            payload["exception_class"] = self.exception_class
        if self.exception_message is not None:
            payload["exception_message"] = self.exception_message
        if self.response_shape is not None:
            payload["response_shape"] = self.response_shape.to_dict()
        return payload


@dataclass
class CandidateOutcome:
    candidate_index: int
    outcome: str
    rejection_reason: str | None = None
    grounding_detail: str | None = None
    information_need_refs: tuple[str, ...] = ()
    excerpt_length: int = 0
    statement_length: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "candidate_index": self.candidate_index,
            "outcome": self.outcome,
            "information_need_refs": list(self.information_need_refs),
            "excerpt_length": self.excerpt_length,
            "statement_length": self.statement_length,
        }
        if self.rejection_reason is not None:
            payload["rejection_reason"] = self.rejection_reason
        if self.grounding_detail is not None:
            payload["grounding_detail"] = self.grounding_detail
        return payload


@dataclass
class WorkItemTrace:
    queue_index: int
    source_id: str
    source_content_checksum: str
    information_need_ids: tuple[str, ...]
    outer_chunk_index: int
    outer_chunk_normalized_start: int
    outer_chunk_normalized_end: int
    outer_chunk_length: int
    extractor_attempts: int = 0
    extractor_status: str = "pending"
    exception_class: str | None = None
    exception_message: str | None = None
    raw_candidate_count: int = 0
    inner_chunks: list[InnerChunkObservation] = field(default_factory=list)
    candidate_outcomes: list[CandidateOutcome] = field(default_factory=list)
    text_passed_to_extractor_length: int = 0
    grounding_search_start: int | None = None
    grounding_search_end: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "queue_index": self.queue_index,
            "source_id": self.source_id,
            "source_content_checksum": self.source_content_checksum,
            "information_need_ids": list(self.information_need_ids),
            "outer_chunk_index": self.outer_chunk_index,
            "outer_chunk_normalized_start": self.outer_chunk_normalized_start,
            "outer_chunk_normalized_end": self.outer_chunk_normalized_end,
            "outer_chunk_length": self.outer_chunk_length,
            "text_passed_to_extractor_length": self.text_passed_to_extractor_length,
            "extractor_attempts": self.extractor_attempts,
            "extractor_status": self.extractor_status,
            "raw_candidate_count": self.raw_candidate_count,
            "inner_chunks": [item.to_dict() for item in self.inner_chunks],
            "candidate_outcomes": [item.to_dict() for item in self.candidate_outcomes],
        }
        if self.exception_class is not None:
            payload["exception_class"] = self.exception_class
        if self.exception_message is not None:
            payload["exception_message"] = self.exception_message
        if self.grounding_search_start is not None:
            payload["grounding_search_start"] = self.grounding_search_start
        if self.grounding_search_end is not None:
            payload["grounding_search_end"] = self.grounding_search_end
        return payload


@dataclass
class EvidenceExtractionDiagnostics:
    workflow_run_id: str
    sources_discovered: int = 0
    sources_eligible: int = 0
    sources_with_run_context: int = 0
    information_needs_represented: tuple[str, ...] = ()
    outer_chunks: int = 0
    inner_chunks_observed: int = 0
    inner_calls_completed: int = 0
    inner_calls_with_candidates: int = 0
    inner_calls_zero_candidates: int = 0
    inner_calls_exception: int = 0
    queue_items: int = 0
    extractor_attempts: int = 0
    extractor_successes: int = 0
    extractor_failures: int = 0
    extractor_exceptions: dict[str, int] = field(default_factory=dict)
    raw_candidates: int = 0
    rejected_invalid_or_missing_need_ref: int = 0
    rejected_provenance: int = 0
    rejected_grounding: int = 0
    rejected_empty_or_invalid_candidate: int = 0
    dedup_hits: int = 0
    persisted_evidence: int = 0
    budget_stop: bool = False
    evidence_stage_cap_reached: bool = False
    budget_stop_reason: str | None = None
    work_items: list[WorkItemTrace] = field(default_factory=list)
    failure_classification: str = EvidenceStageFailureClassification.SUCCESS.value
    response_classification_counts: dict[str, int] = field(default_factory=dict)

    def record_response_classification(self, classification: str | None) -> None:
        if not classification:
            return
        self.response_classification_counts[classification] = (
            self.response_classification_counts.get(classification, 0) + 1
        )

    def record_exception(self, exc: BaseException) -> None:
        name = type(exc).__name__
        self.extractor_exceptions[name] = self.extractor_exceptions.get(name, 0) + 1

    def classify(
        self,
        *,
        persisted_evidence: int,
        budget_stop_before_any_attempt: bool,
    ) -> str:
        if persisted_evidence > 0 and not self._has_rejections_or_failures():
            self.failure_classification = EvidenceStageFailureClassification.SUCCESS.value
            return self.failure_classification

        if persisted_evidence > 0:
            self.failure_classification = EvidenceStageFailureClassification.MIXED_FAILURE.value
            return self.failure_classification

        if budget_stop_before_any_attempt:
            self.failure_classification = (
                EvidenceStageFailureClassification.BUDGET_EXHAUSTED_BEFORE_EVIDENCE.value
            )
            return self.failure_classification

        if self.sources_eligible == 0:
            if self.sources_discovered == 0:
                self.failure_classification = (
                    EvidenceStageFailureClassification.NO_ELIGIBLE_SOURCES.value
                )
            else:
                self.failure_classification = (
                    EvidenceStageFailureClassification.NO_ELIGIBLE_SOURCES.value
                )
            return self.failure_classification

        if self.queue_items == 0:
            if self.sources_with_run_context == 0:
                self.failure_classification = (
                    EvidenceStageFailureClassification.NO_RUN_SCOPED_CONTEXT.value
                )
            else:
                self.failure_classification = (
                    EvidenceStageFailureClassification.EMPTY_EXTRACTION_QUEUE.value
                )
            return self.failure_classification

        categories: set[str] = set()
        if self.extractor_failures > 0 or self.extractor_exceptions:
            categories.add(EvidenceStageFailureClassification.EXTRACTOR_FAILURE.value)
        if self.raw_candidates == 0 and self.extractor_attempts > 0 and not self.extractor_exceptions:
            categories.add(EvidenceStageFailureClassification.NO_CANDIDATES.value)
        if self.rejected_invalid_or_missing_need_ref > 0:
            categories.add(EvidenceStageFailureClassification.INVALID_NEED_REFS_ALL.value)
        if self.rejected_provenance > 0:
            categories.add(EvidenceStageFailureClassification.PROVENANCE_REJECTED_ALL.value)
        if self.rejected_grounding > 0:
            categories.add(EvidenceStageFailureClassification.GROUNDING_REJECTED_ALL.value)

        if len(categories) == 0:
            if self.budget_stop and persisted_evidence == 0:
                self.failure_classification = (
                    EvidenceStageFailureClassification.BUDGET_EXHAUSTED_BEFORE_EVIDENCE.value
                )
            elif self.extractor_attempts == 0:
                self.failure_classification = (
                    EvidenceStageFailureClassification.NO_RUN_SCOPED_CONTEXT.value
                )
            else:
                self.failure_classification = EvidenceStageFailureClassification.NO_CANDIDATES.value
            return self.failure_classification

        if len(categories) == 1:
            self.failure_classification = next(iter(categories))
            return self.failure_classification

        self.failure_classification = EvidenceStageFailureClassification.MIXED_FAILURE.value
        return self.failure_classification

    def _has_rejections_or_failures(self) -> bool:
        return any(
            (
                self.extractor_failures > 0,
                self.rejected_invalid_or_missing_need_ref > 0,
                self.rejected_provenance > 0,
                self.rejected_grounding > 0,
                self.rejected_empty_or_invalid_candidate > 0,
                bool(self.extractor_exceptions),
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "workflow_run_id": self.workflow_run_id,
            "sources_discovered": self.sources_discovered,
            "sources_eligible": self.sources_eligible,
            "sources_with_run_context": self.sources_with_run_context,
            "information_needs_represented": list(self.information_needs_represented),
            "outer_chunks": self.outer_chunks,
            "inner_chunks_observed": self.inner_chunks_observed,
            "inner_calls_completed": self.inner_calls_completed,
            "inner_calls_with_candidates": self.inner_calls_with_candidates,
            "inner_calls_zero_candidates": self.inner_calls_zero_candidates,
            "inner_calls_exception": self.inner_calls_exception,
            "queue_items": self.queue_items,
            "extractor_attempts": self.extractor_attempts,
            "extractor_successes": self.extractor_successes,
            "extractor_failures": self.extractor_failures,
            "extractor_exceptions": dict(self.extractor_exceptions),
            "raw_candidates": self.raw_candidates,
            "rejected_invalid_or_missing_need_ref": self.rejected_invalid_or_missing_need_ref,
            "rejected_provenance": self.rejected_provenance,
            "rejected_grounding": self.rejected_grounding,
            "rejected_empty_or_invalid_candidate": self.rejected_empty_or_invalid_candidate,
            "dedup_hits": self.dedup_hits,
            "persisted_evidence": self.persisted_evidence,
            "budget_stop": self.budget_stop,
            "evidence_stage_cap_reached": self.evidence_stage_cap_reached,
            "budget_stop_reason": self.budget_stop_reason,
            "failure_classification": self.failure_classification,
            "work_items": [item.to_dict() for item in self.work_items],
        }
        if self.response_classification_counts:
            payload["response_classification_counts"] = dict(
                self.response_classification_counts,
            )
        return payload


_current_diagnostics: ContextVar[EvidenceExtractionDiagnostics | None] = ContextVar(
    "evidence_extraction_diagnostics",
    default=None,
)
_current_work_item: ContextVar[WorkItemTrace | None] = ContextVar(
    "evidence_extraction_work_item",
    default=None,
)


def activate_diagnostics(diagnostics: EvidenceExtractionDiagnostics):
    return _current_diagnostics.set(diagnostics)


def deactivate_diagnostics(token) -> None:
    _current_diagnostics.reset(token)


def get_active_diagnostics() -> EvidenceExtractionDiagnostics | None:
    return _current_diagnostics.get()


def set_active_work_item(work_item: WorkItemTrace | None):
    return _current_work_item.set(work_item)


def reset_active_work_item(token) -> None:
    _current_work_item.reset(token)


def get_active_work_item() -> WorkItemTrace | None:
    return _current_work_item.get()


def record_inner_chunk_observation(observation: InnerChunkObservation) -> None:
    diagnostics = get_active_diagnostics()
    work_item = get_active_work_item()
    if diagnostics is not None:
        diagnostics.inner_chunks_observed += 1
        if observation.response_shape is not None:
            diagnostics.record_response_classification(
                observation.response_shape.response_classification,
            )
        if observation.extractor_status == "exception":
            diagnostics.inner_calls_exception += 1
        elif observation.extractor_status == "success":
            diagnostics.inner_calls_completed += 1
            if observation.raw_candidate_count > 0:
                diagnostics.inner_calls_with_candidates += 1
            else:
                diagnostics.inner_calls_zero_candidates += 1
    if work_item is not None:
        work_item.inner_chunks.append(observation)


def classify_grounding_failure(
    *,
    source_text: str,
    excerpt: str,
    chunk_normalized_start: int | None,
    chunk_normalized_end: int | None,
) -> str:
    normalized_excerpt = normalize_source_text(excerpt)
    if not normalized_excerpt:
        return "empty_excerpt"

    bounded = locate_excerpt(
        source_text=source_text,
        excerpt=excerpt,
        search_start=chunk_normalized_start or 0,
        search_end=chunk_normalized_end,
    )
    if bounded is not None:
        return "grounded_in_window"

    unbounded = locate_excerpt(source_text=source_text, excerpt=excerpt)
    if unbounded is None:
        return "excerpt_not_found"

    if chunk_normalized_start is not None or chunk_normalized_end is not None:
        return "offset_mismatch"

    return "normalization_mismatch"


def classify_provenance_rejection(message: str) -> str:
    lowered = message.lower()
    if "information_need_refs" in lowered and "outside" in lowered:
        return CandidateRejectionReason.INVALID_NEED_REF.value
    return CandidateRejectionReason.PROVENANCE.value

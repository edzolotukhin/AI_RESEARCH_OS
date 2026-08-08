from __future__ import annotations

from application.runtime.task_result_codec import capture_task_result
from application.evidence.evidence_extraction_service import EvidenceExtractionSummary

from runtime.workflow_context import WorkflowContext

EVIDENCE_EXTRACTION_SHARED_KEY = "evidence_extraction"


def has_evidence_failure_diagnostics(context: WorkflowContext) -> bool:
    """Return True when shared state contains structured evidence diagnostics."""
    payload = context.read_shared(EVIDENCE_EXTRACTION_SHARED_KEY)
    if not isinstance(payload, dict):
        return False
    diagnostics = payload.get("diagnostics")
    return isinstance(diagnostics, dict)


def persist_evidence_failure_diagnostics(
    context: WorkflowContext,
    summary: EvidenceExtractionSummary,
) -> None:
    """Write evidence diagnostics to shared state before task failure propagates."""
    context.write_shared(EVIDENCE_EXTRACTION_SHARED_KEY, summary.to_dict())
    task = context.current_task
    if task is not None:
        context.intermediate_results[task.id] = capture_task_result(
            context,
            task.id,
        )


def try_persist_evidence_failure_diagnostics(
    context: WorkflowContext,
    summary: EvidenceExtractionSummary,
) -> BaseException | None:
    """Persist diagnostics without masking the original evidence failure."""
    try:
        persist_evidence_failure_diagnostics(context, summary)
    except Exception as exc:
        return exc
    return None

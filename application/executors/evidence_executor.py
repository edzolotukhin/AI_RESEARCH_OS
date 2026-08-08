from __future__ import annotations

from application.contracts.base_executor import BaseExecutor
from application.evidence.exceptions import EvidenceExtractionError
from application.evidence.evidence_failure_diagnostics_persistence import (
    try_persist_evidence_failure_diagnostics,
)
from application.runtime.task_result_codec import capture_task_result
from application.evidence.evidence_extraction_service import EvidenceExtractionService

from runtime.workflow_context import WorkflowContext


class EvidenceExecutor(BaseExecutor):
    """Desk-research evidence extraction stage executor (DR-04)."""

    def __init__(
        self,
        *,
        evidence_extraction_service: EvidenceExtractionService,
    ) -> None:
        self._evidence_extraction_service = evidence_extraction_service

    def run(self, context: WorkflowContext) -> WorkflowContext:
        try:
            summary = self._evidence_extraction_service.extract_for_context(context)
        except EvidenceExtractionError as exc:
            if exc.summary is not None:
                persistence_error = try_persist_evidence_failure_diagnostics(
                    context,
                    exc.summary,
                )
                if persistence_error is not None:
                    errors = context.execution_metadata.setdefault(
                        "evidence_diagnostics_persistence_errors",
                        [],
                    )
                    errors.append(
                        {
                            "error_type": type(persistence_error).__name__,
                            "error_message": str(persistence_error),
                        },
                    )
            raise

        context.write_shared("evidence_extraction", summary.to_dict())

        task = context.current_task
        if task is not None:
            context.intermediate_results[task.id] = capture_task_result(
                context,
                task.id,
            )
        return context

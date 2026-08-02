from __future__ import annotations

from application.contracts.base_executor import BaseExecutor
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
        summary = self._evidence_extraction_service.extract_for_context(context)
        context.write_shared("evidence_extraction", summary.to_dict())

        task = context.current_task
        if task is not None:
            context.intermediate_results[task.id] = capture_task_result(
                context,
                task.id,
            )
        return context

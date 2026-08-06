from __future__ import annotations

from application.runtime.checkpoint_context import CHECKPOINT_SERVICE_KEY
from runtime.workflow_context import WorkflowContext


def checkpoint_loop_progress(context: WorkflowContext) -> None:
    """Persist in-task loop progress before the next paid research operation."""
    checkpoint = context.services.get(CHECKPOINT_SERVICE_KEY)
    if checkpoint is None:
        return
    on_progress = getattr(checkpoint, "on_task_progress", None)
    if callable(on_progress):
        on_progress(context)

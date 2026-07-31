from __future__ import annotations

from typing import Protocol

from application.scheduling.scheduling_result import SchedulingResult
from runtime.workflow_context import WorkflowContext


class WorkflowRuntimeCheckpoint(Protocol):
    """Application port invoked by WorkflowEngine during durable execution."""

    def on_workflow_started(self, context: WorkflowContext) -> None:
        ...

    def on_scheduling(
        self,
        context: WorkflowContext,
        scheduling_result: SchedulingResult,
    ) -> None:
        ...

    def on_task_running(self, context: WorkflowContext) -> None:
        ...

    def on_task_finished(
        self,
        context: WorkflowContext,
        *,
        error: BaseException | None,
    ) -> None:
        ...

    def on_workflow_finalized(
        self,
        context: WorkflowContext,
        *,
        error: BaseException | None,
    ) -> None:
        ...

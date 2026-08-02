from __future__ import annotations

from application.contracts.base_executor import BaseExecutor
from application.exceptions.capability_not_implemented_error import (
    CapabilityNotImplementedError,
)

from runtime.workflow_context import WorkflowContext


class UnimplementedCapabilityExecutor(BaseExecutor):
    """Production placeholder that fails explicitly before any success transition."""

    def __init__(self, *, capability: str, stage: str) -> None:
        self._capability = capability
        self._stage = stage

    def run(self, context: WorkflowContext) -> WorkflowContext:
        task = context.current_task
        raise CapabilityNotImplementedError(
            capability=self._capability,
            stage=self._stage,
            task_id=task.definition_id if task is not None else None,
        )


class DeterministicStageExecutor(BaseExecutor):
    """
    Test/smoke-only stub for infrastructure verification.

    Must not be registered unless ApplicationConfig.deterministic_stage_executors
    is explicitly enabled.
    """

    def __init__(self, *, stage_key: str) -> None:
        self._stage_key = stage_key

    def run(self, context: WorkflowContext) -> WorkflowContext:
        completed = list(context.read_shared("_deterministic_stages_completed") or [])
        completed.append(self._stage_key)
        context.write_shared("_deterministic_stages_completed", completed)
        return context

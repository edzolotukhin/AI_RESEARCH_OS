from runtime.workflow_context import WorkflowContext

from application.executor_resolver import ExecutorResolver
from application.execution.execution_budget_context import (
    set_execution_stage,
    stage_for_executor,
)
from application.quantitative.execution_diagnostics import semantic_call_recording_scope
from application.ports.workflow_runtime_checkpoint import WorkflowRuntimeCheckpoint
from application.runtime.checkpoint_context import CHECKPOINT_SERVICE_KEY
from application.task_lifecycle_manager import TaskLifecycleManager
from domain.value_objects.task_status import TaskStatus


class TaskExecutor:
    """
    Выполняет задачи посредством зарегистрированных Executor'ов.
    """

    def __init__(
        self,
        resolver: ExecutorResolver,
        lifecycle: TaskLifecycleManager,
    ):
        self._resolver = resolver
        self._lifecycle = lifecycle

    def execute(
        self,
        context: WorkflowContext,
        *,
        runtime_checkpoint: WorkflowRuntimeCheckpoint | None = None,
    ) -> WorkflowContext:
        task = context.current_task

        if task is None:
            raise ValueError("WorkflowContext.current_task is not set.")

        self._lifecycle.start(task)
        if runtime_checkpoint is not None:
            context.services[CHECKPOINT_SERVICE_KEY] = runtime_checkpoint
            runtime_checkpoint.on_task_running(context)

        executor = self._resolver.resolve(task)

        try:
            set_execution_stage(stage_for_executor(task.executor_id))
            with semantic_call_recording_scope(context, runtime_checkpoint):
                context = executor.run(context)
            # A methodology checkpoint may deliberately pause a running task.
            # Completion remains owned by the lifecycle only for non-paused work.
            if task.status != TaskStatus.PAUSED:
                self._lifecycle.complete(task)

            return context

        except Exception:
            self._lifecycle.fail(task)

            raise
        finally:
            set_execution_stage(None)

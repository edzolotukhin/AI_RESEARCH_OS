from runtime.workflow_context import WorkflowContext

from application.executor_resolver import ExecutorResolver
from application.task_lifecycle_manager import TaskLifecycleManager


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
    ) -> WorkflowContext:
        task = context.current_task

        if task is None:
            raise ValueError("WorkflowContext.current_task is not set.")

        self._lifecycle.start(task)

        executor = self._resolver.resolve(task)

        try:
            context = executor.run(context)

            self._lifecycle.complete(task)

            return context

        except Exception:
            self._lifecycle.fail(task)

            raise

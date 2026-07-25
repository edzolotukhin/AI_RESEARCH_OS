from runtime.research_context import ResearchContext

from domain.task import Task

from application.executor_resolver import ExecutorResolver
from application.task_lifecycle_manager import TaskLifecycleManager


class TaskExecutor:
    """
    Выполняет одну Task целиком.

    Отвечает за:
    - получение Executor;
    - жизненный цикл Task;
    - выполнение Task.
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
        task: Task,
        context: ResearchContext,
    ) -> ResearchContext:

        self._lifecycle.start(task)

        try:
            executor = self._resolver.resolve(task.executor_id)

            context.current_task = task

            context = executor.run(
                task=task,
                context=context,
            )

            self._lifecycle.complete(task)

            return context

        except Exception:
            self._lifecycle.fail(task)
            raise
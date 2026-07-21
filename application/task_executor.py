from domain.task import Task
from runtime.research_context import ResearchContext

from application.factories.executor_factory import ExecutorFactory
from application.executor_resolver import ExecutorResolver
from application.task_lifecycle_manager import TaskLifecycleManager


class TaskExecutor:
    """
    Выполняет одну Task целиком.

    Отвечает за:
    - выбор Executor;
    - жизненный цикл Task;
    - выполнение Task.
    """

    def __init__(self, registry):
        self._resolver = ExecutorResolver(registry)
        self._factory = ExecutorFactory()
        self._lifecycle = TaskLifecycleManager()

    def execute(
        self,
        task: Task,
        context: ResearchContext,
    ) -> ResearchContext:

        self._lifecycle.start(task)

        try:
            executor_cls = self._resolver.resolve(task.executor_id)
            executor = self._factory.create(executor_cls)

            context.current_task = task

            context = executor.run(context)

            self._lifecycle.complete(task)

            return context

        except Exception:
            self._lifecycle.fail(task)
            raise
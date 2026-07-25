from agency.agency import Agency

from runtime.research_context import ResearchContext

from domain.task_definition import TaskDefinition

from application.task_executor import TaskExecutor
from application.executor_resolver import ExecutorResolver
from application.task_lifecycle_manager import TaskLifecycleManager


def main():
    agency = Agency()

    print(f"Initialized: {agency.initialized}")

    agency.initialize()

    print(f"Initialized: {agency.initialized}")

    # Создаем проект
    project = agency.create_project("Architecture Test")

    print(f"Project created: {project.name}")

    # Создаем описание задачи
    definition = TaskDefinition(
        id="build_research_plan",
        name="Build Research Plan",
        executor_id="planner",
    )

    # Создаем экземпляр задачи
    task = agency.task_factory.create(definition)

    print(f"Task created: {task.name}")

    # Создаем контекст выполнения
    context = ResearchContext(
        project=project,
    )

    # Создаем зависимости
    resolver = ExecutorResolver(agency.registry)
    lifecycle = TaskLifecycleManager()

    # Создаем TaskExecutor
    task_executor = TaskExecutor(
        resolver=resolver,
        lifecycle=lifecycle,
    )

    # Выполняем задачу
    context = task_executor.execute(
        task=task,
        context=context,
    )

    print(f"Execution state: {context.state}")

    if context.current_task:
        print(f"Current task: {context.current_task.name}")
        print(f"Executor: {context.current_task.executor_id}")

    agency.shutdown()

    print(f"Initialized: {agency.initialized}")


if __name__ == "__main__":
    main()
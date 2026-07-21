from agency.agency import Agency

from runtime.research_context import ResearchContext

from domain.task_definition import TaskDefinition

from application.task_executor import TaskExecutor


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

    # Выполняем задачу
    task_executor = TaskExecutor(
        agency.registry,
    )

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
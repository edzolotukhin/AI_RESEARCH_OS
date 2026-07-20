from agency.agency import Agency

from runtime.research_context import ResearchContext


def main():
    agency = Agency()

    print(f"Initialized: {agency.initialized}")

    agency.initialize()

    print(f"Initialized: {agency.initialized}")

    # Создаем проект
    project = agency.create_project("Architecture Test")

    print(f"Project created: {project.name}")

    # Создаем первую задачу
    task = agency.task_factory.create(
        name="Build Research Plan",
        description="Create research execution plan",
        assigned_agent="planner",
    )

    print(f"Task created: {task.name}")

    # Создаем контекст выполнения
    context = ResearchContext(
        project=project,
    )

    context.current_task = task

    # Получаем PlannerAgent из Registry
    planner_cls = agency.registry.agents.get("planner")

    planner = planner_cls()

    # Выполняем задачу
    context = planner.run(context)

    print(f"Execution state: {context.state}")

    if context.current_task:
        print(f"Current task: {context.current_task.name}")
        print(f"Assigned agent: {context.current_task.assigned_agent}")

    agency.shutdown()

    print(f"Initialized: {agency.initialized}")


if __name__ == "__main__":
    main()
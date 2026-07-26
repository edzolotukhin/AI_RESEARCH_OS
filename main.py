from agency.agency import Agency

from domain.project_brief import ProjectBrief
from domain.task_definition import TaskDefinition

from runtime.research_context import ResearchContext


def main():

    agency = Agency()

    print(f"Initialized: {agency.initialized}")

    agency.initialize()

    print(f"Initialized: {agency.initialized}")

    project = agency.create_project("Architecture Test")

    project.brief = ProjectBrief(
        client="Purina",
        project_title="Brand Health 2026",
        business_problem=(
            "Assess the current market position of the brand."
        ),
        research_goal=(
            "Evaluate brand awareness, usage and loyalty."
        ),
    )

    print(f"Project created: {project.name}")

    definition = TaskDefinition(
        id="build_research_plan",
        name="Build Research Plan",
        executor_id="planner",
    )

    task = agency.task_factory.create(definition)

    print(f"Task created: {task.name}")

    context = ResearchContext(
        project=project,
    )

    context = agency.task_executor.execute(
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
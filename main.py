from application.composition_root import create_application

from domain.project_brief import ProjectBrief


def main():

    agency = create_application()

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

    context = agency.start_research(project)

    print(f"Workflow run: {context.workflow_run.id}")
    print(f"Workflow status: {context.workflow_run.status}")

    if context.current_task:
        print(f"Current task: {context.current_task.name}")
        print(f"Executor: {context.current_task.executor_id}")

    agency.shutdown()

    print(f"Initialized: {agency.initialized}")


if __name__ == "__main__":
    main()

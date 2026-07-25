from domain.workflow_template import WorkflowTemplate
from domain.task_definition import TaskDefinition


class PlannerService:
    """
    Строит WorkflowTemplate для проекта.
    """

    def build_workflow(
        self,
        project,
    ) -> WorkflowTemplate:

        template = WorkflowTemplate(
            id="research_workflow",
            name="Research Workflow",
        )

        template.task_definitions.extend([
            TaskDefinition(
                id="client_qualification",
                name="Client Qualification",
                executor_id="planner",
            ),
            TaskDefinition(
                id="project_brief",
                name="Project Brief",
                executor_id="planner",
                depends_on=["client_qualification"],
            ),
        ])

        return template
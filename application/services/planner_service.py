from uuid import uuid4

from domain.ai.llm_response import LLMResponse
from domain.project import Project
from domain.workflow_template import WorkflowTemplate
from domain.workflow_template_builder import WorkflowTemplateBuilder


class PlannerService:
    """
    Builds a workflow template from the planner LLM response.
    """

    def build_workflow(
        self,
        project: Project,
        response: LLMResponse,
    ) -> WorkflowTemplate:
        """
        Temporary implementation.

        The planner response is accepted but is not yet parsed.
        Parsing will be implemented in PlannerResponseParser.
        """

        builder = WorkflowTemplateBuilder(
            id=str(uuid4()),
            name=f"Workflow for {project.name}",
        )

        return builder.build()
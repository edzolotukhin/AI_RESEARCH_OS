from agents.planner.planner_agent import PlannerAgent

from application.prompts.builders.planner_prompt_builder import (
    PlannerPromptBuilder,
)
from application.prompts.file_template_loader import FileTemplateLoader
from application.prompts.python_format_prompt_renderer import (
    PythonFormatPromptRenderer,
)
from application.services.planner_service import PlannerService


class PlannerAgentFactory:
    """
    Factory создания PlannerAgent.
    """

    def create(
        self,
    ) -> PlannerAgent:

        planner_service = PlannerService()

        template_loader = FileTemplateLoader()

        prompt_renderer = PythonFormatPromptRenderer()

        prompt_builder = PlannerPromptBuilder(
            template_loader=template_loader,
            prompt_renderer=prompt_renderer,
        )

        return PlannerAgent(
            planner_service=planner_service,
            prompt_builder=prompt_builder,
        )
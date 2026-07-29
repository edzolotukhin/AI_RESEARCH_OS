from pathlib import Path

from application.prompts.builders.prompt_builder import PromptBuilder
from application.prompts.prompt_renderer import PromptRenderer
from application.prompts.template_loader import TemplateLoader

from domain.ai.prompt import Prompt

from runtime.workflow_context import WorkflowContext


class PlannerPromptBuilder(PromptBuilder):
    """
    Builds prompts for the PlannerAgent.
    """

    SYSTEM_TEMPLATE = Path(
        "application/prompts/templates/planner/system.md"
    )

    USER_TEMPLATE = Path(
        "application/prompts/templates/planner/user.md"
    )

    def __init__(
        self,
        template_loader: TemplateLoader,
        prompt_renderer: PromptRenderer,
    ) -> None:
        self._template_loader = template_loader
        self._prompt_renderer = prompt_renderer

    def build(
        self,
        context: WorkflowContext,
    ) -> Prompt:
        project = context.project

        if project.brief is None:
            raise ValueError(
                "ProjectBrief is required to build planner prompt."
            )

        brief = project.brief

        variables = {
            "client": brief.client,
            "project_title": brief.project_title,
            "business_problem": brief.business_problem,
            "research_goal": brief.research_goal,
        }

        system_template = self._template_loader.load(
            self.SYSTEM_TEMPLATE,
        )

        user_template = self._template_loader.load(
            self.USER_TEMPLATE,
        )

        system_prompt = self._prompt_renderer.render(
            system_template,
            variables,
        )

        user_prompt = self._prompt_renderer.render(
            user_template,
            variables,
        )

        return Prompt(
            system=system_prompt,
            user=user_prompt,
        )

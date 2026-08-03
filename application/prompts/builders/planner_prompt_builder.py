from pathlib import Path

from application.planner.executor_catalog import ExecutorCatalog
from application.planner.planner_bounds import PlannerBounds
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
        executor_catalog: ExecutorCatalog,
        bounds: PlannerBounds | None = None,
    ) -> None:
        self._template_loader = template_loader
        self._prompt_renderer = prompt_renderer
        self._executor_catalog = executor_catalog
        self._bounds = bounds or PlannerBounds.from_env()

    def build(
        self,
        context: WorkflowContext,
    ) -> Prompt:
        project = context.project

        if project.research_brief is None:
            raise ValueError(
                "ResearchBrief is required to build planner prompt."
            )

        brief = project.research_brief

        variables = {
            "title": brief.title,
            "business_question": brief.business_question,
            "objectives": _format_list(brief.objectives),
            "geography": _format_list(brief.geography),
            "market": brief.market or "Not specified",
            "target_entities": _format_list(brief.target_entities),
            "timeframe": brief.timeframe or "Not specified",
            "constraints": _format_list(brief.constraints),
            "deliverables": _format_list(brief.deliverables),
            "language": brief.language,
            "context": brief.context or "Not specified",
            "known_information": _format_list(brief.known_information),
            "exclusions": _format_list(brief.exclusions),
            "executor_catalog": self._executor_catalog.format_for_prompt(),
            "planner_bounds": self._bounds.format_for_prompt(),
            "planner_compact_instruction": self._bounds.format_compact_instruction(),
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


def _format_list(items: tuple[str, ...]) -> str:
    if not items:
        return "None specified"
    return "\n".join(f"- {item}" for item in items)

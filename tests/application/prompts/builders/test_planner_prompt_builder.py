from unittest.mock import Mock

from application.prompts.builders.planner_prompt_builder import (
    PlannerPromptBuilder,
)

from domain.ai.prompt import Prompt
from domain.project import Project
from domain.project_brief import ProjectBrief

from runtime.research_context import ResearchContext


def test_build_returns_prompt():

    template_loader = Mock()
    prompt_renderer = Mock()

    template_loader.load.side_effect = [
        "system template",
        "user template",
    ]

    prompt_renderer.render.side_effect = [
        "system prompt",
        "user prompt",
    ]

    builder = PlannerPromptBuilder(
        template_loader=template_loader,
        prompt_renderer=prompt_renderer,
    )

    project = Project(
        id="1",
        name="Architecture Test",
    )

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

    context = ResearchContext(
        project=project,
    )

    prompt = builder.build(context)

    assert isinstance(prompt, Prompt)

    assert prompt.system == "system prompt"
    assert prompt.user == "user prompt"

    assert template_loader.load.call_count == 2
    assert prompt_renderer.render.call_count == 2


def test_build_raises_when_project_brief_is_missing():

    template_loader = Mock()
    prompt_renderer = Mock()

    builder = PlannerPromptBuilder(
        template_loader=template_loader,
        prompt_renderer=prompt_renderer,
    )

    project = Project(
        id="1",
        name="Architecture Test",
    )

    context = ResearchContext(
        project=project,
    )

    try:
        builder.build(context)
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert (
            str(exc)
            == "ProjectBrief is required to build planner prompt."
        )
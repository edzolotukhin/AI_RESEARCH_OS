from unittest.mock import Mock

from application.planner.executor_catalog import ExecutorCatalog
from application.planner.executor_definitions import AGENT_EXECUTOR_CAPABILITIES
from application.prompts.builders.planner_prompt_builder import (
    PlannerPromptBuilder,
)

from domain.ai.prompt import Prompt
from domain.project import Project
from tests.fixtures.research_brief import sample_research_brief

from domain.workflow_run import WorkflowRun

from runtime.workflow_context import WorkflowContext


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
        executor_catalog=ExecutorCatalog.from_capabilities(
            AGENT_EXECUTOR_CAPABILITIES,
        ),
    )

    project = Project(
        id="1",
        name="Architecture Test",
    )

    project.research_brief = sample_research_brief(
        business_question="Assess the current market position of the brand.",
        objectives=("Evaluate brand awareness, usage and loyalty.",),
    )

    context = WorkflowContext(
        workflow_run=WorkflowRun(id="planning"),
        project=project,
    )

    prompt = builder.build(context)

    assert isinstance(prompt, Prompt)

    assert prompt.system == "system prompt"
    assert prompt.user == "user prompt"

    assert template_loader.load.call_count == 2
    assert prompt_renderer.render.call_count == 2

    render_variables = prompt_renderer.render.call_args_list[0].args[1]
    assert "executor_catalog" in render_variables
    assert "planner" in render_variables["executor_catalog"]


def test_build_raises_when_project_brief_is_missing():

    template_loader = Mock()
    prompt_renderer = Mock()

    builder = PlannerPromptBuilder(
        template_loader=template_loader,
        prompt_renderer=prompt_renderer,
        executor_catalog=ExecutorCatalog.from_capabilities(
            AGENT_EXECUTOR_CAPABILITIES,
        ),
    )

    project = Project(
        id="1",
        name="Architecture Test",
    )

    context = WorkflowContext(
        workflow_run=WorkflowRun(id="planning"),
        project=project,
    )

    try:
        builder.build(context)
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert (
            str(exc)
            == "ResearchBrief is required to build planner prompt."
        )

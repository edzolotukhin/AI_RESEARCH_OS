import tempfile
import unittest
from unittest.mock import Mock

from agency.agency import Agency
from application.composition_root import create_application
from application.config import ApplicationConfig, ApplicationOverrides

from domain.ai.llm_response import LLMResponse

from loaders.agent_loader import AgentLoader

from runtime.workflow_context import WorkflowContext

from tests.fixtures.planner_responses import (
    TRUNCATED_PLANNER_JSON,
    UNKNOWN_EXECUTOR_PLANNER_JSON,
    VALID_PLANNER_JSON,
)
from tests.fixtures.research_brief import sample_research_brief


def _project_with_brief(name: str = "Brand Health 2026") -> object:
    project = Mock()
    project.research_brief = sample_research_brief(title=name)
    return project


class AgencyLazyInitializationTests(unittest.TestCase):

    def _create_agency(self, temp_dir: str, mock_llm: Mock):
        return create_application(
            config=ApplicationConfig(
                projects_root=temp_dir,
                deterministic_stage_executors=True,
            ),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )

    def test_start_research_lazy_initializes_agency(self):
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content=VALID_PLANNER_JSON)

        with tempfile.TemporaryDirectory() as temp_dir:
            agency = self._create_agency(temp_dir, mock_llm)
            load_calls: list[int] = []
            original_load = agency._agent_loader.load

            def tracking_load() -> None:
                load_calls.append(1)
                original_load()

            agency._agent_loader.load = tracking_load

            self.assertFalse(agency.initialized)

            project = agency.create_project("Brand Health 2026")
            project.research_brief = _project_with_brief().research_brief

            context = agency.start_research(project)

        self.assertEqual(load_calls, [1])
        self.assertTrue(agency.initialized)
        self.assertIsInstance(context, WorkflowContext)
        self.assertIsNotNone(context.workflow_run)

    def test_explicit_initialize_is_not_repeated_by_start_research(self):
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content=VALID_PLANNER_JSON)

        with tempfile.TemporaryDirectory() as temp_dir:
            agency = self._create_agency(temp_dir, mock_llm)
            load_calls: list[int] = []
            original_load = agency._agent_loader.load

            def tracking_load() -> None:
                load_calls.append(1)
                original_load()

            agency._agent_loader.load = tracking_load

            agency.initialize()
            project = agency.create_project("Brand Health 2026")
            project.research_brief = _project_with_brief().research_brief

            context = agency.start_research(project)

        self.assertEqual(load_calls, [1])
        self.assertTrue(agency.initialized)
        self.assertIsInstance(context, WorkflowContext)

    def test_two_start_research_calls_load_executors_once(self):
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content=VALID_PLANNER_JSON)

        with tempfile.TemporaryDirectory() as temp_dir:
            agency = self._create_agency(temp_dir, mock_llm)
            load_calls: list[int] = []
            original_load = agency._agent_loader.load

            def tracking_load() -> None:
                load_calls.append(1)
                original_load()

            agency._agent_loader.load = tracking_load

            project_one = agency.create_project("Brand Health 2026")
            project_one.research_brief = _project_with_brief("Brand Health 2026").research_brief

            project_two = agency.create_project("Brand Health 2027")
            project_two.research_brief = _project_with_brief("Brand Health 2027").research_brief

            context_one = agency.start_research(project_one)
            context_two = agency.start_research(project_two)

        self.assertEqual(load_calls, [1])
        self.assertTrue(agency.initialized)
        self.assertIsNotNone(context_one.workflow_run)
        self.assertIsNotNone(context_two.workflow_run)
        self.assertGreaterEqual(mock_llm.generate.call_count, 2)

    def test_start_research_propagates_initialization_failure(self):
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content=VALID_PLANNER_JSON)

        with tempfile.TemporaryDirectory() as temp_dir:
            agency = self._create_agency(temp_dir, mock_llm)
            agency._agent_loader.load = Mock(
                side_effect=RuntimeError("loader failed"),
            )
            agency._planner_agent = Mock()
            agency._workflow_engine = Mock()

            project = agency.create_project("Brand Health 2026")
            project.research_brief = _project_with_brief().research_brief

            with self.assertRaises(RuntimeError) as ctx:
                agency.start_research(project)

            self.assertEqual(str(ctx.exception), "loader failed")
            self.assertFalse(agency.initialized)
            agency._planner_agent.run.assert_not_called()
            agency._workflow_engine.execute.assert_not_called()

    def test_initialize_twice_remains_safe(self):
        loader = Mock(spec=AgentLoader)
        agency = Agency(
            agent_loader=loader,
            project_service=Mock(),
            planner_agent=Mock(),
            workflow_run_factory=Mock(),
            workflow_engine=Mock(),
        )

        agency.initialize()
        agency.initialize()

        self.assertEqual(loader.load.call_count, 2)
        self.assertTrue(agency.initialized)


class AgencyStartResearchTests(unittest.TestCase):

    def test_start_research_without_real_openai(self):
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=VALID_PLANNER_JSON,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            agency = create_application(
                config=ApplicationConfig(
                    projects_root=temp_dir,
                    deterministic_stage_executors=True,
                ),
                overrides=ApplicationOverrides(
                    llm_client=mock_llm,
                ),
            )
            agency.initialize()

            project = agency.create_project("Brand Health 2026")
            project.research_brief = sample_research_brief()

            context = agency.start_research(project)

        self.assertIsInstance(context, WorkflowContext)
        self.assertIsNotNone(context.workflow_template)
        self.assertEqual(len(context.workflow_template.task_definitions), 4)
        self.assertIsNotNone(context.workflow_run)
        self.assertEqual(len(context.workflow_run.tasks), 4)
        mock_llm.generate.assert_called()

    def test_start_research_retries_after_truncated_planner_response(self):
        mock_llm = Mock()
        mock_llm.generate.side_effect = [
            LLMResponse(
                content=TRUNCATED_PLANNER_JSON,
                finish_reason="length",
                output_tokens=4096,
                max_output_tokens=4096,
            ),
            LLMResponse(
                content=VALID_PLANNER_JSON,
                finish_reason="stop",
            ),
            LLMResponse(
                content=VALID_PLANNER_JSON,
                finish_reason="stop",
            ),
            LLMResponse(
                content=VALID_PLANNER_JSON,
                finish_reason="stop",
            ),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            agency = create_application(
                config=ApplicationConfig(
                    projects_root=temp_dir,
                    deterministic_stage_executors=True,
                ),
                overrides=ApplicationOverrides(
                    llm_client=mock_llm,
                ),
            )
            agency.initialize()

            project = agency.create_project("Brand Health 2026")
            project.research_brief = sample_research_brief()

            context = agency.start_research(project)

        self.assertIsInstance(context, WorkflowContext)
        self.assertIsNotNone(context.workflow_template)
        self.assertEqual(len(context.workflow_template.task_definitions), 4)
        self.assertGreaterEqual(mock_llm.generate.call_count, 2)
        self.assertLessEqual(mock_llm.generate.call_count, 4)

    def test_start_research_retries_unknown_executor_and_resolves_first_task(self):
        mock_llm = Mock()
        mock_llm.generate.side_effect = [
            LLMResponse(content=UNKNOWN_EXECUTOR_PLANNER_JSON),
            LLMResponse(content=VALID_PLANNER_JSON, finish_reason="stop"),
            LLMResponse(content=VALID_PLANNER_JSON, finish_reason="stop"),
            LLMResponse(content=VALID_PLANNER_JSON, finish_reason="stop"),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            agency = create_application(
                config=ApplicationConfig(
                    projects_root=temp_dir,
                    deterministic_stage_executors=True,
                ),
                overrides=ApplicationOverrides(
                    llm_client=mock_llm,
                ),
            )
            agency.initialize()

            project = agency.create_project("Brand Health 2026")
            project.research_brief = sample_research_brief()

            context = agency.start_research(project)

        self.assertIsNotNone(context.workflow_run)
        self.assertGreaterEqual(mock_llm.generate.call_count, 2)
        self.assertIn(
            context.workflow_run.tasks[0].executor_id,
            {"planner", "search", "analysis", "report", "proposal"},
        )


if __name__ == "__main__":
    unittest.main()

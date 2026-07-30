import inspect
import unittest
from unittest.mock import Mock

from agents.base_agent import BaseAgent
from agents.planner.planner_executor import PlannerExecutor

from application.contracts.base_executor import BaseExecutor
from application.executor_resolver import ExecutorResolver
from application.executors.agent_executor import AgentExecutor
from application.task_executor import TaskExecutor
from application.task_lifecycle_manager import TaskLifecycleManager
from application.workflow_engine import WorkflowEngine

from domain.project import Project
from domain.value_objects.executor_type import ExecutorType
from domain.value_objects.task_status import TaskStatus
from domain.workflow_run import WorkflowRun

from registry.agent_registry import AgentRegistry
from registry.api_executor_registry import APIExecutorRegistry
from registry.human_executor_registry import HumanExecutorRegistry
from registry.tool_registry import ToolRegistry

from runtime.workflow_context import WorkflowContext

from tests.helpers.workflow_run_builder import make_task, make_workflow_run


class StubAgent(BaseAgent):

    def __init__(self, name: str = "stub") -> None:
        super().__init__(name)

    def run(
        self,
        context: WorkflowContext,
    ) -> WorkflowContext:
        context.write_shared("stub_completed", True)
        return context


class ExecutorLayerTests(unittest.TestCase):

    def test_agent_executor_calls_agent_run(self):
        agent = Mock(spec=BaseAgent)
        agent.run.side_effect = lambda context: context

        executor = AgentExecutor(agent=agent)
        task = make_task("task-1", executor_id="stub", status=TaskStatus.READY)
        context = WorkflowContext(
            workflow_run=make_workflow_run(task),
            project=Project(id="p1", name="Test"),
            current_task=task,
        )

        result = executor.run(context)

        agent.run.assert_called_once_with(context)
        self.assertIs(result, context)
        self.assertIn(task.id, result.intermediate_results)

    def test_planner_executor_follows_common_model(self):
        self.assertTrue(issubclass(PlannerExecutor, AgentExecutor))
        self.assertTrue(issubclass(PlannerExecutor, BaseExecutor))

        agent = Mock()
        agent.run.side_effect = lambda context: context
        executor = PlannerExecutor(agent=agent)

        task = make_task("task-1", executor_id="planner", status=TaskStatus.READY)
        context = WorkflowContext(
            workflow_run=make_workflow_run(task),
            project=Project(id="p1", name="Test"),
            current_task=task,
        )

        executor.run(context)
        agent.run.assert_called_once_with(context)

    def test_resolver_contains_no_business_logic(self):
        source = inspect.getsource(ExecutorResolver)

        for keyword in (
            "planner",
            "search",
            "analysis",
            "report",
            "proposal",
            "llm",
            "workflow_template",
        ):
            self.assertNotIn(keyword, source.lower())

    def test_new_agent_connects_without_engine_changes(self):
        agent_registry = AgentRegistry()
        resolver = ExecutorResolver(
            agent_registry=agent_registry,
            tool_registry=ToolRegistry(),
            human_registry=HumanExecutorRegistry(),
            api_registry=APIExecutorRegistry(),
        )

        stub_executor = AgentExecutor(agent=StubAgent(name="custom"))
        agent_registry.register("custom", stub_executor)

        task = make_task(
            "task-custom",
            executor_id="custom",
            executor_type=ExecutorType.AGENT,
        )

        executor = resolver.resolve(task)

        self.assertIsInstance(executor, AgentExecutor)
        self.assertEqual(executor.agent.name, "custom")

    def test_task_executor_does_not_reference_concrete_agents(self):
        source = inspect.getsource(TaskExecutor)

        for keyword in (
            "PlannerAgent",
            "SearchAgent",
            "AnalysisAgent",
            "ReportAgent",
            "ProposalAgent",
        ):
            self.assertNotIn(keyword, source)

    def test_workflow_engine_does_not_reference_concrete_agents(self):
        source = inspect.getsource(WorkflowEngine)

        for keyword in (
            "PlannerAgent",
            "SearchAgent",
            "AnalysisAgent",
            "ReportAgent",
            "ProposalAgent",
            "AgentExecutor",
        ):
            self.assertNotIn(keyword, source)

    def test_new_agent_runs_through_task_executor(self):
        agent_registry = AgentRegistry()
        resolver = ExecutorResolver(
            agent_registry=agent_registry,
            tool_registry=ToolRegistry(),
            human_registry=HumanExecutorRegistry(),
            api_registry=APIExecutorRegistry(),
        )
        agent_registry.register(
            "search",
            AgentExecutor(agent=StubAgent(name="search")),
        )

        task_executor = TaskExecutor(
            resolver=resolver,
            lifecycle=TaskLifecycleManager(),
        )

        task = make_task(
            "task-search",
            executor_id="search",
            executor_type=ExecutorType.AGENT,
            status=TaskStatus.READY,
        )
        context = WorkflowContext(
            workflow_run=make_workflow_run(task),
            project=Project(id="p1", name="Test"),
            current_task=task,
        )

        result = task_executor.execute(context)

        self.assertTrue(result.read_shared("stub_completed"))
        self.assertIn(task.id, result.intermediate_results)


if __name__ == "__main__":
    unittest.main()

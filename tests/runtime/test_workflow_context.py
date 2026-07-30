import unittest

from application.task_scheduler import TaskScheduler

from domain.project import Project
from domain.workflow_template import WorkflowTemplate

from runtime.workflow_context import WorkflowContext

from tests.helpers.workflow_run_builder import make_task, make_workflow_run


class WorkflowContextTests(unittest.TestCase):

    def setUp(self):
        self.project = Project(id="p1", name="Test Project")
        self.workflow_template = WorkflowTemplate(
            id="template-1",
            name="Template",
        )
        self.workflow_run = make_workflow_run(
            make_task("a"),
            run_id="run-1",
        )

    def test_workflow_context_stores_workflow_run(self):
        context = WorkflowContext(
            workflow_run=self.workflow_run,
            project=self.project,
            workflow_template=self.workflow_template,
        )

        self.assertIs(context.workflow_run, self.workflow_run)
        self.assertEqual(context.workflow_run.id, "run-1")

    def test_task_can_read_shared_state(self):
        context = WorkflowContext(
            workflow_run=self.workflow_run,
            project=self.project,
        )
        context.write_shared("status", "ready")

        self.assertEqual(context.read_shared("status"), "ready")

    def test_task_can_write_shared_state(self):
        context = WorkflowContext(
            workflow_run=self.workflow_run,
            project=self.project,
        )

        context.write_shared("result", {"score": 10})

        self.assertEqual(
            context.shared_state["result"],
            {"score": 10},
        )

    def test_scheduler_continues_to_work_with_workflow_run(self):
        scheduler = TaskScheduler()
        task_a = make_task("a")
        task_b = make_task("b", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b)

        ready = scheduler.get_next_task(workflow_run)

        self.assertIs(ready, task_a)

    def test_executor_resolver_works_without_context_changes(self):
        from unittest.mock import Mock

        from application.exceptions.executor_error import ExecutorNotFoundError
        from application.executor_resolver import ExecutorResolver
        from domain.value_objects.executor_type import ExecutorType
        from registry.agent_registry import AgentRegistry
        from registry.api_executor_registry import APIExecutorRegistry
        from registry.human_executor_registry import HumanExecutorRegistry
        from registry.tool_registry import ToolRegistry

        agent_registry = AgentRegistry()
        executor = Mock()
        agent_registry.register("planner", executor)

        resolver = ExecutorResolver(
            agent_registry=agent_registry,
            tool_registry=ToolRegistry(),
            human_registry=HumanExecutorRegistry(),
            api_registry=APIExecutorRegistry(),
        )

        task = make_task(
            "task-1",
            executor_id="planner",
            executor_type=ExecutorType.AGENT,
        )

        resolved = resolver.resolve(task)

        self.assertIs(resolved, executor)

        missing = make_task(
            "task-2",
            executor_id="missing",
            executor_type=ExecutorType.AGENT,
        )

        with self.assertRaises(ExecutorNotFoundError):
            resolver.resolve(missing)


if __name__ == "__main__":
    unittest.main()

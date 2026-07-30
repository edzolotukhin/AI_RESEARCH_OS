import unittest
from unittest.mock import Mock

from application.exceptions.executor_error import (
    ExecutorNotFoundError,
    InvalidExecutorConfigurationError,
    UnsupportedExecutorTypeError,
)
from application.executor_resolver import ExecutorResolver

from domain.value_objects.executor_type import ExecutorType

from registry.agent_registry import AgentRegistry
from registry.api_executor_registry import APIExecutorRegistry
from registry.human_executor_registry import HumanExecutorRegistry
from registry.tool_registry import ToolRegistry

from tests.helpers.workflow_run_builder import make_task


class ExecutorResolverTests(unittest.TestCase):

    def setUp(self):
        self.agent_registry = AgentRegistry()
        self.tool_registry = ToolRegistry()
        self.human_registry = HumanExecutorRegistry()
        self.api_registry = APIExecutorRegistry()

        self.resolver = ExecutorResolver(
            agent_registry=self.agent_registry,
            tool_registry=self.tool_registry,
            human_registry=self.human_registry,
            api_registry=self.api_registry,
        )

        self.agent_executor = Mock()
        self.tool_executor = Mock()
        self.human_executor = Mock()
        self.api_executor = Mock()

        self.agent_registry.register("planner", self.agent_executor)
        self.tool_registry.register("search", self.tool_executor)
        self.human_registry.register("review", self.human_executor)
        self.api_registry.register("crm_sync", self.api_executor)

    def test_agent_executor_is_resolved(self):
        task = make_task(
            "task-1",
            executor_id="planner",
            executor_type=ExecutorType.AGENT,
        )

        executor = self.resolver.resolve(task)

        self.assertIs(executor, self.agent_executor)

    def test_tool_executor_is_resolved(self):
        task = make_task(
            "task-1",
            executor_id="search",
            executor_type=ExecutorType.TOOL,
        )

        executor = self.resolver.resolve(task)

        self.assertIs(executor, self.tool_executor)

    def test_human_executor_is_resolved(self):
        task = make_task(
            "task-1",
            executor_id="review",
            executor_type=ExecutorType.HUMAN,
        )

        executor = self.resolver.resolve(task)

        self.assertIs(executor, self.human_executor)

    def test_api_executor_is_resolved(self):
        task = make_task(
            "task-1",
            executor_id="crm_sync",
            executor_type=ExecutorType.API,
        )

        executor = self.resolver.resolve(task)

        self.assertIs(executor, self.api_executor)

    def test_unknown_executor_id_raises_not_found(self):
        task = make_task(
            "task-1",
            executor_id="missing",
            executor_type=ExecutorType.AGENT,
        )

        with self.assertRaises(ExecutorNotFoundError):
            self.resolver.resolve(task)

    def test_unknown_executor_type_raises_unsupported(self):
        task = make_task(
            "task-1",
            executor_id="planner",
            executor_type=ExecutorType.AGENT,
        )
        task.executor_type = "invalid"

        with self.assertRaises(UnsupportedExecutorTypeError):
            self.resolver.resolve(task)

    def test_empty_executor_id_raises_invalid_configuration(self):
        task = make_task(
            "task-1",
            executor_id="",
            executor_type=ExecutorType.AGENT,
        )

        with self.assertRaises(InvalidExecutorConfigurationError):
            self.resolver.resolve(task)


if __name__ == "__main__":
    unittest.main()

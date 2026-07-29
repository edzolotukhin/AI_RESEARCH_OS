from application.contracts.base_executor import BaseExecutor
from application.exceptions.executor_error import (
    ExecutorNotFoundError,
    InvalidExecutorConfigurationError,
    UnsupportedExecutorTypeError,
)

from domain.task import Task
from domain.value_objects.executor_type import ExecutorType

from registry.agent_registry import AgentRegistry
from registry.api_executor_registry import APIExecutorRegistry
from registry.human_executor_registry import HumanExecutorRegistry
from registry.tool_registry import ToolRegistry


class ExecutorResolver:
    """
    Resolves a BaseExecutor for a Task based on explicit executor_type.
    """

    def __init__(
        self,
        agent_registry: AgentRegistry,
        tool_registry: ToolRegistry,
        human_registry: HumanExecutorRegistry,
        api_registry: APIExecutorRegistry,
    ) -> None:
        self._agent_registry = agent_registry
        self._tool_registry = tool_registry
        self._human_registry = human_registry
        self._api_registry = api_registry

    def resolve(
        self,
        task: Task,
    ) -> BaseExecutor:
        executor_id = task.executor_id.strip()

        if not executor_id:
            raise InvalidExecutorConfigurationError(
                f"Task '{task.definition_id}' has an empty executor_id."
            )

        executor_type = task.executor_type

        if executor_type is None:
            raise InvalidExecutorConfigurationError(
                f"Task '{task.definition_id}' has no executor_type."
            )

        executor = self._lookup_executor(
            executor_type,
            executor_id,
        )

        if executor is None:
            raise ExecutorNotFoundError(
                executor_type,
                executor_id,
            )

        return executor

    def _lookup_executor(
        self,
        executor_type: ExecutorType,
        executor_id: str,
    ):
        if executor_type == ExecutorType.AGENT:
            return self._agent_registry.get(executor_id)

        if executor_type == ExecutorType.TOOL:
            return self._tool_registry.get(executor_id)

        if executor_type == ExecutorType.HUMAN:
            return self._human_registry.get(executor_id)

        if executor_type == ExecutorType.API:
            return self._api_registry.get(executor_id)

        raise UnsupportedExecutorTypeError(executor_type)

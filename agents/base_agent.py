from abc import ABC, abstractmethod

from runtime.workflow_context import WorkflowContext


class BaseAgent(ABC):
    """
    Base class for AI agents.

    Agents own all domain logic and exchange state exclusively through
    WorkflowContext.
    """

    def __init__(
        self,
        name: str = "",
    ) -> None:
        self.name = name

    @abstractmethod
    def run(
        self,
        context: WorkflowContext,
    ) -> WorkflowContext:
        pass

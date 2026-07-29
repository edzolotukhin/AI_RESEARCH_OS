from abc import ABC, abstractmethod

from runtime.workflow_context import WorkflowContext


class BaseExecutor(ABC):
    """
    Infrastructure contract for task executors.

    Implementations receive WorkflowContext, delegate work to the
    appropriate runtime component (Agent, Tool, API, Human), and return
    the updated context. They must not contain business logic.
    """

    @abstractmethod
    def run(
        self,
        context: WorkflowContext,
    ) -> WorkflowContext:
        pass

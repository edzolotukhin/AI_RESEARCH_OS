from abc import ABC, abstractmethod

from domain.ai.prompt import Prompt

from runtime.workflow_context import WorkflowContext


class PromptBuilder(ABC):
    """
    Builds a Prompt from the current workflow context.
    """

    @abstractmethod
    def build(
        self,
        context: WorkflowContext,
    ) -> Prompt:
        pass

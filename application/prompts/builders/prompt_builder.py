from abc import ABC, abstractmethod

from domain.ai.prompt import Prompt
from runtime.research_context import ResearchContext


class PromptBuilder(ABC):
    """
    Builds a Prompt from the current research context.
    """

    @abstractmethod
    def build(
        self,
        context: ResearchContext,
    ) -> Prompt:
        """
        Build an immutable Prompt.
        """
        ...
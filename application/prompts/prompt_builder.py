from abc import ABC, abstractmethod

from domain.ai.prompt import Prompt


class PromptBuilder(ABC):
    """
    Builds a Prompt from application context.
    """

    @abstractmethod
    def build(self) -> Prompt:
        """
        Build an immutable Prompt.
        """
        pass
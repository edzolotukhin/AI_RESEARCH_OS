from abc import ABC, abstractmethod

from domain.ai.prompt import Prompt
from domain.ai.llm_response import LLMResponse
from infrastructure.llm.generation_options import LLMGenerationOptions


class LLMClient(ABC):
    """
    Abstract interface for communicating with a Large Language Model.
    """

    @abstractmethod
    def generate(
        self,
        prompt: Prompt,
        *,
        options: LLMGenerationOptions | None = None,
    ) -> LLMResponse:
        """
        Generate a response from an LLM.
        """
        pass

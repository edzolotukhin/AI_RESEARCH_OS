from openai import OpenAI

from domain.ai.prompt import Prompt
from domain.ai.llm_response import LLMResponse

from infrastructure.llm.llm_client import LLMClient
from infrastructure.llm.llm_configuration import LLMConfiguration


class OpenAIClient(LLMClient):
    """
    OpenAI implementation of the LLMClient interface.
    """

    def __init__(
        self,
        configuration: LLMConfiguration,
    ):
        self._configuration = configuration
        self._client = OpenAI()

    def generate(
        self,
        prompt: Prompt,
    ) -> LLMResponse:

        response = self._client.responses.create(
            model=self._configuration.model,
            temperature=self._configuration.temperature,
            max_output_tokens=self._configuration.max_tokens,
            input=[
                {
                    "role": "system",
                    "content": prompt.system,
                },
                {
                    "role": "user",
                    "content": prompt.user,
                },
            ],
        )

        return LLMResponse(
            content=response.output_text,
        )
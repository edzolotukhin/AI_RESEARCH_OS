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
        self._client = None

    def generate(
        self,
        prompt: Prompt,
    ) -> LLMResponse:
        client = self._get_client()

        response = client.responses.create(
            model=self._configuration.model,
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
            max_output_tokens=self._configuration.max_tokens,
        )

        return LLMResponse(
            content=response.output_text,
        )

    def _get_client(self):
        if self._client is None:
            from dotenv import load_dotenv
            from openai import OpenAI

            load_dotenv()
            self._client = OpenAI()

        return self._client

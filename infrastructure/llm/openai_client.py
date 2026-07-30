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
            finish_reason=self._resolve_finish_reason(response),
            output_tokens=self._resolve_output_tokens(response),
            max_output_tokens=self._configuration.max_tokens,
        )

    @staticmethod
    def _resolve_finish_reason(response) -> str | None:
        status = getattr(response, "status", None)

        if status == "completed":
            return "stop"

        incomplete_details = getattr(response, "incomplete_details", None)

        if incomplete_details is None:
            return status

        reason = getattr(incomplete_details, "reason", None)

        if reason == "max_output_tokens":
            return "length"

        return reason or status

    @staticmethod
    def _resolve_output_tokens(response) -> int | None:
        usage = getattr(response, "usage", None)

        if usage is None:
            return None

        return getattr(usage, "output_tokens", None)

    def _get_client(self):
        if self._client is None:
            from dotenv import load_dotenv
            from openai import OpenAI

            load_dotenv()
            self._client = OpenAI()

        return self._client

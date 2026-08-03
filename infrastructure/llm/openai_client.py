from domain.ai.prompt import Prompt
from domain.ai.llm_response import LLMResponse

from infrastructure.llm.generation_options import LLMGenerationOptions
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
        *,
        options: LLMGenerationOptions | None = None,
    ) -> LLMResponse:
        client = self._get_client()

        max_output_tokens = (
            options.max_output_tokens
            if options and options.max_output_tokens is not None
            else self._configuration.max_tokens
        )
        reasoning_effort = (
            options.reasoning_effort
            if options and options.reasoning_effort
            else None
        )

        request_kwargs = {
            "model": self._configuration.model,
            "input": [
                {
                    "role": "system",
                    "content": prompt.system,
                },
                {
                    "role": "user",
                    "content": prompt.user,
                },
            ],
            "max_output_tokens": max_output_tokens,
        }

        if reasoning_effort:
            request_kwargs["reasoning"] = {"effort": reasoning_effort}

        response = client.responses.create(**request_kwargs)

        return LLMResponse(
            content=response.output_text,
            finish_reason=self._resolve_finish_reason(response),
            output_tokens=self._resolve_output_tokens(response),
            max_output_tokens=max_output_tokens,
            reasoning_tokens=self._resolve_reasoning_tokens(response),
            incomplete_reason=self._resolve_incomplete_reason(response),
            configured_reasoning_effort=reasoning_effort,
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
    def _resolve_incomplete_reason(response) -> str | None:
        incomplete_details = getattr(response, "incomplete_details", None)

        if incomplete_details is None:
            return None

        return getattr(incomplete_details, "reason", None)

    @staticmethod
    def _resolve_output_tokens(response) -> int | None:
        usage = getattr(response, "usage", None)

        if usage is None:
            return None

        return getattr(usage, "output_tokens", None)

    @staticmethod
    def _resolve_reasoning_tokens(response) -> int | None:
        usage = getattr(response, "usage", None)

        if usage is None:
            return None

        details = getattr(usage, "output_tokens_details", None)

        if details is None:
            return None

        return getattr(details, "reasoning_tokens", None)

    def _get_client(self):
        if self._client is None:
            from dotenv import load_dotenv
            from openai import OpenAI

            load_dotenv()
            self._client = OpenAI()

        return self._client

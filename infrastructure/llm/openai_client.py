from hashlib import sha256

from application.quantitative.execution_diagnostics import (
    get_semantic_call_recorder,
    semantic_stage,
)
from domain.ai.prompt import Prompt
from domain.ai.llm_response import LLMResponse

from infrastructure.llm.generation_options import LLMGenerationOptions
from infrastructure.llm.llm_client import LLMClient
from infrastructure.llm.llm_configuration import LLMConfiguration


_REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def model_supports_reasoning(model: str) -> bool:
    """Fail-safe local capability gate for model-specific request options."""
    normalized = model.strip().casefold()
    return any(
        normalized == prefix or normalized.startswith(f"{prefix}-")
        for prefix in _REASONING_MODEL_PREFIXES
    )


class OpenAIClient(LLMClient):
    """
    OpenAI implementation of the LLMClient interface.
    """

    def __init__(
        self,
        configuration: LLMConfiguration,
        *,
        max_retries: int | None = None,
        timeout_seconds: float | None = None,
    ):
        self._configuration = configuration
        self._max_retries = max_retries
        self._timeout_seconds = timeout_seconds
        self._client = None

    def generate(
        self,
        prompt: Prompt,
        *,
        options: LLMGenerationOptions | None = None,
    ) -> LLMResponse:
        recorder = get_semantic_call_recorder()
        stage = semantic_stage()
        call_id = None
        if recorder is not None and stage is not None:
            call_id = recorder.planned(
                stage=stage,
                provider="openai",
                model=self._configuration.model,
                input_fingerprint=sha256((prompt.system + "\n" + prompt.user).encode()).hexdigest(),
            )
        try:
            client = self._get_client()
        except Exception as exc:
            if recorder is not None and call_id is not None:
                recorder.failed(call_id, exc, after_dispatch=False)
            raise

        max_output_tokens = (
            options.max_output_tokens
            if options and options.max_output_tokens is not None
            else self._configuration.max_tokens
        )
        configured_reasoning_effort = (
            options.reasoning_effort
            if options and options.reasoning_effort
            else None
        )
        reasoning_effort = (
            configured_reasoning_effort
            if configured_reasoning_effort
            and model_supports_reasoning(self._configuration.model)
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

        if recorder is not None and call_id is not None:
            recorder.dispatched(call_id)
        try:
            response = client.responses.create(**request_kwargs)
        except Exception as exc:
            if recorder is not None and call_id is not None:
                recorder.failed(call_id, exc, after_dispatch=True)
            raise

        if recorder is not None and call_id is not None:
            recorder.returned(call_id, sha256((response.output_text or "").encode()).hexdigest())

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
            kwargs = {}
            if self._max_retries is not None:
                kwargs["max_retries"] = self._max_retries
            if self._timeout_seconds is not None:
                kwargs["timeout"] = self._timeout_seconds
            self._client = OpenAI(**kwargs)

        return self._client

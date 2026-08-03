from dataclasses import dataclass


@dataclass(frozen=True)
class LLMGenerationOptions:
    """
    Per-request overrides for Responses API generation.
    """

    max_output_tokens: int | None = None
    reasoning_effort: str | None = None

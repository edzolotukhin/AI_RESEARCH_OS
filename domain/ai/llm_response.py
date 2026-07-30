from dataclasses import dataclass


@dataclass(frozen=True)
class LLMResponse:
    """
    Immutable response returned by an LLM.
    """

    content: str
    finish_reason: str | None = None
    output_tokens: int | None = None
    max_output_tokens: int | None = None

    @property
    def was_truncated(self) -> bool:
        if self.finish_reason is None:
            return False

        normalized = self.finish_reason.lower()

        return normalized in {
            "length",
            "max_output_tokens",
            "max_tokens",
            "incomplete",
        }

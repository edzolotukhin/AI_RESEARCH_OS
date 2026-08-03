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
    reasoning_tokens: int | None = None
    incomplete_reason: str | None = None
    configured_reasoning_effort: str | None = None

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

    @property
    def visible_output_length(self) -> int:
        return len(self.content or "")

    @property
    def reasoning_budget_exhausted(self) -> bool:
        from domain.ai.reasoning_budget import is_reasoning_budget_exhaustion

        return is_reasoning_budget_exhaustion(self)

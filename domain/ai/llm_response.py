from dataclasses import dataclass


@dataclass(frozen=True)
class LLMResponse:
    """
    Immutable response returned by an LLM.
    """

    content: str
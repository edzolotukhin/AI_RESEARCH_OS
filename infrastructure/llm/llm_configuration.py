from dataclasses import dataclass


@dataclass(frozen=True)
class LLMConfiguration:
    """
    Configuration for an LLM client.
    """

    model: str
    temperature: float = 0.0
    max_tokens: int = 4096
from dataclasses import dataclass


@dataclass(frozen=True)
class Prompt:
    """
    Immutable prompt passed to an LLM.
    """

    system: str
    user: str
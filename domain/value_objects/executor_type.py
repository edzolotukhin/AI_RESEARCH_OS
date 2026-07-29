from enum import Enum


class ExecutorType(str, Enum):
    """
    Explicit executor category for task execution.
    """

    AGENT = "agent"
    TOOL = "tool"
    HUMAN = "human"
    API = "api"

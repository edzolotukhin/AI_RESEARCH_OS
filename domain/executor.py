from dataclasses import dataclass
from enum import Enum


class ExecutorType(Enum):
    AGENT = "agent"
    HUMAN = "human"
    TOOL = "tool"
    API = "api"
    SCRIPT = "script"
    WORKFLOW = "workflow"


@dataclass(frozen=True)
class Executor:
    """
    Универсальный исполнитель задачи.

    Это не реализация выполнения.
    Это описание того, кто способен выполнить Task.
    """

    id: str

    name: str

    type: ExecutorType
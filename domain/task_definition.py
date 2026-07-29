from dataclasses import dataclass, field
from typing import Any

from domain.value_objects.executor_type import ExecutorType


@dataclass
class TaskDefinition:
    id: str
    name: str
    executor_id: str
    executor_type: ExecutorType = ExecutorType.AGENT

    depends_on: list[str] = field(default_factory=list)

    metadata: dict[str, Any] = field(default_factory=dict)

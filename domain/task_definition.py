from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskDefinition:
    id: str
    name: str
    executor_id: str

    depends_on: list[str] = field(default_factory=list)

    metadata: dict[str, Any] = field(default_factory=dict)
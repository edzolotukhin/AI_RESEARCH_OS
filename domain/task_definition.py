from dataclasses import dataclass, field


@dataclass
class TaskDefinition:
    """
    Неизменяемое описание одного шага Workflow.
    """

    id: str

    title: str

    agent: str

    goal: str = ""

    inputs: list[str] = field(default_factory=list)

    outputs: list[str] = field(default_factory=list)

    dependencies: list[str] = field(default_factory=list)
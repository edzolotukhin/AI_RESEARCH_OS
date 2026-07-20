from dataclasses import dataclass, field

from domain.ai_task import AITask


@dataclass
class WorkflowRun:
    """
    Конкретный экземпляр выполнения Workflow.
    """

    id: str

    template_id: str

    tasks: list[AITask] = field(default_factory=list)
from dataclasses import dataclass, field

from domain.research_brief import ResearchBrief
from domain.task_definition import TaskDefinition


@dataclass
class WorkflowTemplate:
    """
    Immutable workflow definition snapshot.

    TaskDefinition entities define runnable tasks. research_brief_snapshot
    captures the research intent at planning time (DR-01).
    """

    id: str

    name: str

    task_definitions: list[TaskDefinition] = field(default_factory=list)

    research_brief_snapshot: ResearchBrief | None = None

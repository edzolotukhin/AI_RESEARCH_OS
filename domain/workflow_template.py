from dataclasses import dataclass, field

from domain.planning.research_design import ResearchDesign
from domain.research_brief import ResearchBrief
from domain.task_definition import TaskDefinition


@dataclass
class WorkflowTemplate:
    """
    Immutable workflow definition snapshot.

    TaskDefinition entities define runnable tasks. Snapshots capture research
    intent and semantic design at planning time (DR-01 / DR-02).
    """

    id: str

    name: str

    task_definitions: list[TaskDefinition] = field(default_factory=list)

    research_brief_snapshot: ResearchBrief | None = None

    research_design_snapshot: ResearchDesign | None = None

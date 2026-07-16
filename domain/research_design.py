from dataclasses import dataclass, field
from typing import List


@dataclass
class ResearchDesign:

    project_title: str

    research_goal: str
    research_objectives: str

    target_audience: str
    geography: str

    methodology: List[str] = field(default_factory=list)

    sample_design: str = ""

    deliverables: List[str] = field(default_factory=list)

    estimated_timing: str = ""

    comments: str = ""

    status: str = "Draft"
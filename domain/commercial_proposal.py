from dataclasses import dataclass, field
from typing import List


@dataclass
class CommercialProposal:

    client: str
    project_title: str

    research_goal: str
    research_objectives: str

    target_audience: str
    geography: str

    recommended_method: str = ""
    sample_size: str = ""
    timing: str = ""
    budget: str = ""

    deliverables: List[str] = field(default_factory=list)

    status: str = "Draft"
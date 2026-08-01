from dataclasses import dataclass, field
from typing import Optional

from domain.client_request import ClientRequest
from domain.client_qualification import ClientQualification
from domain.project_brief import ProjectBrief
from domain.research_design import ResearchDesign
from domain.workflow_run import WorkflowRun
from domain.value_objects.project_status import ProjectStatus


@dataclass
class Project:
    id: str

    name: str

    status: str = ProjectStatus.LEAD

    client_request: Optional[ClientRequest] = None

    qualification: Optional[ClientQualification] = None

    brief: Optional[ProjectBrief] = None

    research_design: Optional[ResearchDesign] = None

    created_at: str = ""

    updated_at: str = ""

    owner_principal_id: str | None = None

    runs: list[WorkflowRun] = field(default_factory=list)

    def start_research_design(self):
        self.status = ProjectStatus.RESEARCH_DESIGN

    def send_to_client_approval(self):
        self.status = ProjectStatus.CLIENT_APPROVAL

    def approve(self):
        self.status = ProjectStatus.APPROVED

    def start_fieldwork(self):
        self.status = ProjectStatus.FIELDWORK

    def close(self):
        self.status = ProjectStatus.CLOSED

    def archive(self):
        self.status = ProjectStatus.ARCHIVED
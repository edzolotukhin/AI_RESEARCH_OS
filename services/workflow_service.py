from domain.project import Project
from domain.value_objects.project_status import ProjectStatus

from services.project_service import ProjectService


class WorkflowService:

    def __init__(self):

        self.project_service = ProjectService()

        self.workflows = {
            ProjectStatus.LEAD: self.project_service.create_research_design
        }

    def start(self, project: Project):

        workflow = self.workflows.get(project.status)

        if workflow is None:

            raise Exception(
                f"Workflow for status '{project.status}' is not implemented."
            )

        workflow(project)
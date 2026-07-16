from domain.project import Project

from roles.client_manager import ClientManager


class WorkflowEngine:

    def __init__(self):

        self.client_manager = ClientManager()

    def run(
        self,
        project: Project
    ) -> Project:

        project = self.client_manager.execute(project)

        return project
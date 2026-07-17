from core.project_repository import ProjectRepository
from domain.project import Project


class Agency:
    """
    Центральный объект AI Research OS.

    Все операции с проектами должны выполняться через Agency.
    """

    def __init__(self):

        self.project_repository = ProjectRepository()

    def create_project(self, project: Project):

        return self.project_repository.create_project(project)

    def save_project(self, project: Project):

        self.project_repository.save_project(project)
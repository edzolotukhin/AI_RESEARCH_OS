from registry.registry import Registry

from loaders.agent_loader import AgentLoader

from infrastructure.project_repository import ProjectRepository

from domain.factories.project_factory import ProjectFactory
from domain.factories.task_factory import TaskFactory


class Agency:
    """
    Центральный объект AI Research OS.
    """

    def __init__(self):
        self.initialized = False

        # Registry
        self.registry = Registry()

        # Loaders
        self.agent_loader = AgentLoader(self.registry)

        # Factories
        self.project_factory = ProjectFactory()
        self.task_factory = TaskFactory()

        # Repositories
        self.project_repository = ProjectRepository()

    def initialize(self):
        """
        Инициализация платформы.
        """

        self.agent_loader.load()

        self.initialized = True

    def shutdown(self):
        """
        Завершение работы платформы.
        """

        self.initialized = False

    def create_project(self, name: str):
        """
        Создать новый проект.
        """

        project = self.project_factory.create(name)

        self.project_repository.create_project(project)
        self.project_repository.save_project(project)

        return project
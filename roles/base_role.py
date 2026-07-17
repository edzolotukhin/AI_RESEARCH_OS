from abc import ABC, abstractmethod

from domain.project import Project


class BaseRole(ABC):

    @abstractmethod
    def execute(self, project: Project) -> Project:
        """
        Выполнить шаг обработки проекта.
        """
        pass
from abc import ABC, abstractmethod

from domain.project import Project


class AITask(ABC):
    """
    Базовый класс AI-задачи.

    Определяет контракт между Agent и Task.
    """

    @property
    @abstractmethod
    def prompt_name(self) -> str:
        pass

    @abstractmethod
    def build_user_prompt(
        self,
        project: Project,
        knowledge,
    ) -> str:
        pass

    @abstractmethod
    def parse_response(
        self,
        project: Project,
        data: dict,
    ) -> Project:
        pass
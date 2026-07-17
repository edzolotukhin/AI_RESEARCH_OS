from abc import ABC, abstractmethod


class Task(ABC):

    @property
    @abstractmethod
    def prompt_name(self) -> str:
        pass

    @abstractmethod
    def build_user_prompt(self, project) -> str:
        pass

    @abstractmethod
    def parse_response(self, project, data):
        pass
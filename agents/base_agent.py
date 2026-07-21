from abc import abstractmethod

from application.contracts.base_executor import BaseExecutor
from runtime.research_context import ResearchContext


class BaseAgent(BaseExecutor):
    """
    Базовый класс для всех AI-агентов.

    Реализует общий контракт BaseExecutor.
    """

    def __init__(self, name: str = ""):
        self.name = name

    @abstractmethod
    def run(
        self,
        context: ResearchContext,
    ) -> ResearchContext:
        """
        Выполнить работу агента.
        """
        pass
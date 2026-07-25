from abc import ABC, abstractmethod

from domain.task import Task
from runtime.research_context import ResearchContext


class BaseExecutor(ABC):
    """
    Базовый контракт любого исполнителя Task.
    """

    @abstractmethod
    def run(
        self,
        task: Task,
        context: ResearchContext,
    ) -> ResearchContext:
        pass
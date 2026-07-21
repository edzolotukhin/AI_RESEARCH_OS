from abc import ABC, abstractmethod

from runtime.research_context import ResearchContext


class BaseExecutor(ABC):
    """
    Базовый контракт любого исполнителя Task.

    Executor получает ResearchContext,
    выполняет свою работу и возвращает обновленный контекст.
    """

    @abstractmethod
    def run(
        self,
        context: ResearchContext,
    ) -> ResearchContext:
        pass
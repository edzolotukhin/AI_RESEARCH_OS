from abc import ABC, abstractmethod

from runtime.research_context import ResearchContext
from domain.ai_task import AITask


class TaskExecutor(ABC):
    """
    Выполняет одну AITask.
    """

    @abstractmethod
    def execute(
        self,
        task: AITask,
        context: ResearchContext,
    ) -> ResearchContext:
        pass
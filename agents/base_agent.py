from application.services.prompt_builder import PromptBuilder
from application.services.task_executor import TaskExecutor

from infrastructure.llm.openai_service import OpenAIService
from infrastructure.parsers.json_parser import JsonParser


class BaseAgent:

    def __init__(self, name: str = ""):

        self.name = name

        prompt_builder = PromptBuilder()
        llm = OpenAIService()
        parser = JsonParser()

        self.executor = TaskExecutor(
            prompt_builder=prompt_builder,
            llm=llm,
            json_parser=parser,
        )

    @property
    def task(self):
        return None

    def execute(
        self,
        project,
        *knowledge_documents,
    ):

        if self.task is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} does not implement task."
            )

        return self.executor.execute(
            task=self.task,
            project=project,
            *knowledge_documents,
        )
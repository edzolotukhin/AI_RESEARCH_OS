from services.prompt_repository import PromptRepository
from services.knowledge_manager import KnowledgeManager
from services.openai_service import OpenAIService
from services.json_parser import JsonParser


class BaseAgent:

    def __init__(self):

        self.prompt_repository = PromptRepository()
        self.knowledge_manager = KnowledgeManager()
        self.llm = OpenAIService()
        self.json_parser = JsonParser()

    def load_prompt(
        self,
        prompt_name: str
    ) -> str:

        return self.prompt_repository.load(prompt_name)

    def load_knowledge(
        self,
        *documents: str
    ):

        return self.knowledge_manager.load(*documents)

    def ask(
        self,
        system_prompt: str,
        user_prompt: str
    ) -> dict:

        response = self.llm.ask(
            system_prompt,
            user_prompt
        )

        return self.json_parser.parse(response)
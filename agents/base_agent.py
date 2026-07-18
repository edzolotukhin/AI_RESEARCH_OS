from infrastructure.documents.document_loader import DocumentLoader
from infrastructure.llm.openai_service import OpenAIService
from infrastructure.parsers.json_parser import JsonParser
from infrastructure.prompts.prompt_repository import PromptRepository


class BaseAgent:

    def __init__(self, name: str = ""):

        self.name = name

        self.prompt_repository = PromptRepository()
        self.document_loader = DocumentLoader()
        self.llm = OpenAIService()
        self.json_parser = JsonParser()

    def load_prompt(
        self,
        prompt_name: str,
    ) -> str:

        return self.prompt_repository.load(prompt_name)

    def load_knowledge(
        self,
        *documents: str,
    ):

        return self.document_loader.load(*documents)

    def ask(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> dict:

        response = self.llm.ask(
            system_prompt,
            user_prompt,
        )

        return self.json_parser.parse(response)

    def create_user_prompt(self, *parts) -> str:

        return "\n\n".join(
            str(part)
            for part in parts
            if part
        )
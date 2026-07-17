from roles.base_role import BaseRole

from services.prompt_repository import PromptRepository
from services.document_loader import DocumentLoader
from services.openai_service import OpenAIService
from services.json_parser import JsonParser


class BaseAgent(BaseRole):

    def __init__(self):

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

    def execute(self, project):

        system_prompt = self.load_prompt(
            self.prompt_name()
        )

        user_prompt = self.build_user_prompt(
            project
        )

        data = self.ask(
            system_prompt,
            user_prompt
        )

        return self.parse_response(
            project,
            data
        )

    def prompt_name(self) -> str:
        raise NotImplementedError()

    def build_user_prompt(self, project):
        raise NotImplementedError()

    def parse_response(self, project, data):
        raise NotImplementedError()
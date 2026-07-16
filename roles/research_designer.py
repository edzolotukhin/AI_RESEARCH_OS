from domain.project import Project

from constants.prompts import Prompts

from services.prompt_repository import PromptRepository
from services.prompt_builder import PromptBuilder
from services.openai_service import OpenAIService
from services.json_parser import JsonParser
from services.research_design_factory import ResearchDesignFactory


class ResearchDesigner:

    def __init__(self):

        self.prompt_repository = PromptRepository()
        self.prompt_builder = PromptBuilder()
        self.llm = OpenAIService()

    def create(self, project: Project):

        brief = project.brief

        system_prompt = self.prompt_repository.load(
            Prompts.RESEARCH_DESIGNER
        )

        user_prompt = self.prompt_builder.build_project_brief(
            brief
        )

        response = self.llm.ask(
            system_prompt,
            user_prompt
        )

        data = JsonParser.parse(response)

        return ResearchDesignFactory.create(
            brief,
            data
        )
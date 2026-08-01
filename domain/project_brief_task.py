from domain.ai_task import AITask
from domain.project import Project
from domain.research_brief import ResearchBrief

from constants.prompts import Prompts


class ProjectBriefTask(AITask):

    @property
    def prompt_name(self) -> str:
        return Prompts.PROJECT_BRIEF

    def build_user_prompt(
        self,
        project: Project,
        knowledge
    ) -> str:

        return f"""Client Qualification

{project.qualification}"""

    def parse_response(
        self,
        project: Project,
        data: dict
    ) -> Project:

        project.research_brief = ResearchBrief.from_dict(data)

        return project

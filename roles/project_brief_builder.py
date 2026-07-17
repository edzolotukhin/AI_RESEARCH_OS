from domain.project import Project
from domain.project_brief import ProjectBrief

from roles.base_agent import BaseAgent
from constants.prompts import Prompts


class ProjectBriefBuilder(BaseAgent):

    def __init__(self):
        super().__init__()

    def prompt_name(self) -> str:
        return Prompts.PROJECT_BRIEF

    def build_user_prompt(
        self,
        project: Project
    ) -> str:

        return self.create_user_prompt(
            f"""Client Qualification

{project.qualification}"""
        )

    def parse_response(
        self,
        project: Project,
        data: dict
    ) -> Project:

        project.brief = ProjectBrief(
            client=data["client"],
            project_title=data["project_title"],
            business_problem=data["business_problem"],
            research_goal=data["research_goal"],
            research_objectives=data["research_objectives"],
            target_audience=data["target_audience"],
            geography=data["geography"],
            constraints=data["constraints"],
            timeline=data["timeline"],
            comments=data["comments"]
        )

        return project
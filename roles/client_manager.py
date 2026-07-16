from domain.project import Project
from domain.client_qualification import ClientQualification

from constants.prompts import Prompts

from roles.base_agent import BaseAgent


class ClientManager(BaseAgent):

    def __init__(self):

        super().__init__()

    def execute(
        self,
        project: Project
    ) -> Project:

        system_prompt = self.load_prompt(
            Prompts.CLIENT_QUALIFICATION
        )

        knowledge = self.load_knowledge(
            "roles/client_manager.md"
        )

        user_prompt = f"""
Company:
{project.client_request.client_name}

Message:
{project.client_request.message}

Corporate knowledge:

{knowledge.content}
"""

        data = self.ask(
            system_prompt,
            user_prompt
        )

        project.qualification = ClientQualification(

            summary=data["summary"],

            project_understanding=data["project_understanding"],

            understanding_score=data["understanding_score"],

            project_state=data["project_state"],

            next_question=data["next_question"],

            missing_information=data["missing_information"]
        )

        return project
from domain.task import Task
from domain.project import Project
from domain.client_qualification import ClientQualification

from constants.prompts import Prompts


class ClientQualificationTask(Task):

    @property
    def prompt_name(self) -> str:
        return Prompts.CLIENT_QUALIFICATION

    def build_user_prompt(
        self,
        project: Project,
        knowledge,
    ) -> str:

        return "\n\n".join([

            f"""Company:
{project.client_request.client_name}""",

            f"""Message:
{project.client_request.message}""",

            f"""Corporate knowledge:

{knowledge.content}"""
        ])

    def parse_response(
        self,
        project: Project,
        data: dict,
    ) -> Project:

        project.qualification = ClientQualification(

            summary=data["summary"],

            project_understanding=data["project_understanding"],

            understanding_score=data["understanding_score"],

            project_state=data["project_state"],

            next_question=data["next_question"],

            missing_information=data["missing_information"]

        )

        return project
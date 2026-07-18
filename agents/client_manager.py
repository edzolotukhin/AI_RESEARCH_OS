from domain.project import Project
from domain.client_qualification_task import ClientQualificationTask

from roles.base_agent import BaseAgent


class ClientManager(BaseAgent):

    def init(self):
        super().init()

        self.task = ClientQualificationTask()

    def prompt_name(self) -> str:
        return self.task.prompt_name

    def build_user_prompt(
        self,
        project: Project,
    ) -> str:

        knowledge = self.load_knowledge(
            "roles/client_manager.md"
        )

        return self.task.build_user_prompt(
            project,
            knowledge,
        )

    def parse_response(
        self,
        project: Project,
        data: dict,
    ) -> Project:

        return self.task.parse_response(
            project,
            data,
        )
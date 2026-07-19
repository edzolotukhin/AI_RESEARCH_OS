from domain.project_brief_task import ProjectBriefTask

from agents.base_agent import BaseAgent


class ProjectBriefBuilder(BaseAgent):

    def __init__(self):
        super().__init__("Project Brief Builder")
        self._task = ProjectBriefTask()

    @property
    def task(self):
        return self._task
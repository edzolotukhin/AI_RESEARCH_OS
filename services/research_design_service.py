from domain.project import Project

from agents.research_designer.research_designer import ResearchDesigner


class ResearchDesignService:

    def __init__(self):

        self.research_designer = ResearchDesigner()

    def execute(self, project: Project):

        project.research_design = self.research_designer.create(project)

        project.start_research_design()
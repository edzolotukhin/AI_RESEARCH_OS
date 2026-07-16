from domain.project import Project

from services.research_design_service import ResearchDesignService


class ProjectService:

    def __init__(self):

        self.research_design_service = ResearchDesignService()

    def create_research_design(self, project: Project):

        self.research_design_service.execute(project)
from agents.client_manager import ClientManager
from agents.project_brief_builder import ProjectBriefBuilder
from agents.research_designer.research_designer import ResearchDesigner


def create_default_pipeline():

    return [
        ClientManager(),
        ProjectBriefBuilder(),
        ResearchDesigner(),
    ]
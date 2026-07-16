from domain.client_request import ClientRequest
from domain.project_brief import ProjectBrief

from services.project_brief_builder import ProjectBriefBuilder


class ClientRequestService:

    def create_project_brief(
        self,
        request: ClientRequest
    ) -> ProjectBrief:

        data = {
            "client": request.client_name,
            "project_title": "",
            "business_problem": request.message,
            "research_goal": "",
            "research_objectives": [],
            "research_object": "",
            "target_audience": "",
            "geography": "",
            "constraints": [],
            "timeline": "",
            "comments": "",
            "attachments": []
        }

        return ProjectBriefBuilder.build(data)
from domain.project_brief import ProjectBrief


class ProjectBriefBuilder:

    @staticmethod
    def build(data: dict) -> ProjectBrief:

        return ProjectBrief(

            client=data.get("client", ""),

            project_title=data.get("project_title", ""),

            business_problem=data.get("business_problem", ""),

            research_goal=data.get("research_goal", ""),

            research_objectives=data.get("research_objectives", []),

            research_object=data.get("research_object", ""),

            target_audience=data.get("target_audience", ""),

            geography=data.get("geography", ""),

            constraints=data.get("constraints", []),

            timeline=data.get("timeline", ""),

            comments=data.get("comments", ""),

            attachments=data.get("attachments", [])
        )
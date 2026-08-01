from domain.research_brief import ResearchBrief


class ProjectBriefBuilder:

    @staticmethod
    def build(data: dict) -> ResearchBrief:
        return ResearchBrief.from_dict(data)

from domain.project_brief import ProjectBrief
from domain.research_design import ResearchDesign

from constants.research_design_fields import ResearchDesignFields


class ResearchDesignFactory:

    @staticmethod
    def create(
        brief: ProjectBrief,
        data: dict
    ) -> ResearchDesign:

        return ResearchDesign(

            project_title=brief.project_title,

            research_goal=brief.research_goal,

            research_objectives=brief.research_objectives,

            target_audience=brief.target_audience,

            geography=brief.geography,

            methodology=data[ResearchDesignFields.METHODOLOGY],

            sample_design=data[ResearchDesignFields.SAMPLE_DESIGN],

            deliverables=data[ResearchDesignFields.DELIVERABLES],

            estimated_timing=data[ResearchDesignFields.ESTIMATED_TIMING]
        )
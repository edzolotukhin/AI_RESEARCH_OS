from __future__ import annotations

from domain.research_brief import ResearchBrief

from api.schemas.workflow_runs import ResearchBriefResponse


def research_brief_to_response(brief: ResearchBrief | None) -> ResearchBriefResponse | None:
    if brief is None:
        return None
    return ResearchBriefResponse(
        title=brief.title,
        business_question=brief.business_question,
        objectives=list(brief.objectives),
        geography=list(brief.geography),
        market=brief.market,
        target_entities=list(brief.target_entities),
        timeframe=brief.timeframe,
        constraints=list(brief.constraints),
        deliverables=list(brief.deliverables),
        language=brief.language,
        context=brief.context,
        known_information=list(brief.known_information),
        exclusions=list(brief.exclusions),
    )

from __future__ import annotations

from domain.common.exceptions import ValidationError
from domain.research_brief import ResearchBrief


def validate_research_brief(brief: ResearchBrief) -> None:
    """Minimal Desk Research product validation."""
    if not brief.title.strip():
        raise ValidationError("ResearchBrief.title must be non-empty.")
    if not brief.business_question.strip():
        raise ValidationError("ResearchBrief.business_question must be non-empty.")
    if not brief.objectives:
        raise ValidationError(
            "ResearchBrief.objectives must contain at least one objective.",
        )
    if not brief.language.strip():
        raise ValidationError("ResearchBrief.language must be non-empty.")

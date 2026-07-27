"""
AI Research OS

Research plan lifecycle.

Defines the lifecycle states of a ResearchPlan within
the Planning domain.

Responsibilities:
- represent the lifecycle of a research plan;
- provide a stable domain vocabulary;
- remain independent from infrastructure.
"""

from enum import StrEnum


class ResearchPlanStatus(StrEnum):
    """Lifecycle states of a ResearchPlan."""

    DRAFT = "draft"
    GENERATED = "generated"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    COMPILED = "compiled"
    EXECUTED = "executed"
    ARCHIVED = "archived"
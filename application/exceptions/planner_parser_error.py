"""
AI Research OS

Planner parser exception.

Defines exceptions raised while converting external planner
responses into internal DTO objects.
"""


class PlannerParserError(Exception):
    """
    Raised when a planner response cannot be parsed into
    a valid PlannerPlanDTO.
    """

    pass
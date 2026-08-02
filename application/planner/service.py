from __future__ import annotations



from collections.abc import Mapping

from typing import Any



from application.factories.research_plan_factory import ResearchPlanFactory

from application.parsers.planner_response_parser import PlannerResponseParser



from domain.planning.research_plan import ResearchPlan

from domain.project import Project



from .contracts import PlannerService





class PlannerServiceImpl(PlannerService):
    """
    Legacy ResearchPlan builder (DR-01).

    Deprecated: production PlannerAgent uses PlannerDesignServiceImpl.
    Removal condition: delete when ResearchPlan unit tests migrate or retire.
    """



    def __init__(

        self,

        response_parser: PlannerResponseParser,

        plan_factory: ResearchPlanFactory,

    ) -> None:

        self._response_parser = response_parser

        self._plan_factory = plan_factory



    def create_plan(

        self,

        project: Project,

        plan_data: Mapping[str, Any],

    ) -> ResearchPlan:

        dto = self._response_parser.parse(plan_data)



        return self._plan_factory.create(dto)


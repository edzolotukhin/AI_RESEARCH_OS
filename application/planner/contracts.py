from __future__ import annotations



from collections.abc import Mapping

from typing import Any, Protocol



from domain.planning.research_plan import ResearchPlan

from domain.project import Project

from domain.workflow_template import WorkflowTemplate





class PlannerService(Protocol):

    """

    Application contract for creating a domain research plan.

    """



    def create_plan(

        self,

        project: Project,

        plan_data: Mapping[str, Any],

    ) -> ResearchPlan:

        """

        Build a ResearchPlan from structured planner data.

        """

        ...





class WorkflowTemplateMapper(Protocol):

    """

    Application contract for mapping ResearchPlan to WorkflowTemplate.

    """



    def from_research_plan(

        self,

        plan: ResearchPlan,

        project: Project,

    ) -> WorkflowTemplate:

        """

        Convert a ResearchPlan into an executable WorkflowTemplate.

        """

        ...


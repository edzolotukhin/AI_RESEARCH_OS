from domain.workflow_plan import WorkflowPlan

from domain.client_qualification_task import ClientQualificationTask
from domain.project_brief_task import ProjectBriefTask


class PlannerService:

    def build_plan(self, project) -> WorkflowPlan:

        plan = WorkflowPlan()

        plan.add(ClientQualificationTask())
        plan.add(ProjectBriefTask())

        return plan
from __future__ import annotations

from application.query.project_workspace_views import (
    MethodOutputAvailabilityView, MethodWorkspaceView, ProjectBriefSummaryView,
    ProjectListItemView, ProjectListView, ProjectWorkspaceView,
    WorkspaceActionView, WorkspaceMethodState,
)
from application.quantitative.workflow import build_quantitative_workflow_template
from domain.value_objects.task_status import TaskStatus


class ProjectWorkspaceQueryService:
    def __init__(self, *, project_service, workflow_service, quantitative_ui_service,
                 research_result_service) -> None:
        self.projects = project_service
        self.workflows = workflow_service
        self.quantitative = quantitative_ui_service
        self.research_results = research_result_service

    def list(self, *, owner_id: str) -> ProjectListView:
        items = []
        for project in self.projects.list_projects(owner_principal_id=owner_id):
            view = self.get(project.id, owner_id=owner_id)
            items.append(ProjectListItemView(
                project.id, project.name, self._humanize(project.status),
                view.desk.state_label, view.quantitative.state_label,
                bool(view.attention_items),
            ))
        return ProjectListView(tuple(items))

    def get(self, project_id: str, *, owner_id: str) -> ProjectWorkspaceView:
        project = self.projects.get_project(project_id)
        if project.owner_principal_id != owner_id:
            from application.persistence.exceptions import AccessDeniedError
            raise AccessDeniedError(f"Project not found: {project_id}")
        runs = self.workflows.list_workflow_runs_for_project(project_id)
        quant_template_id = build_quantitative_workflow_template().id
        quant_study = None
        quant_run = None
        desk_runs = []
        for run in runs:
            snapshots = self.quantitative.state.list_for_run(
                run.id, project_id=project_id, expected_type=self._study_type()
            ) if self.quantitative is not None else ()
            if snapshots:
                quant_study = max(snapshots, key=lambda item: item.revision)
                quant_run = run
            elif run.workflow_template_id != quant_template_id:
                desk_runs.append(run)
        desk_run = desk_runs[-1] if desk_runs else None
        desk = self._desk(project_id, desk_run)
        quant = self._quant(project_id, quant_study, quant_run)
        brief = None if project.research_brief is None else ProjectBriefSummaryView(
            project.research_brief.title, project.research_brief.business_question,
            project.research_brief.objectives,
        )
        attention = tuple(x.name for x in (desk, quant) if x.state is WorkspaceMethodState.ATTENTION)
        return ProjectWorkspaceView(project.id, project.name, self._humanize(project.status),
                                    brief, desk, quant, attention)

    @staticmethod
    def _study_type():
        from domain.quantitative.workflow import QuantitativeStudyProjection
        return QuantitativeStudyProjection

    def _desk(self, project_id, run):
        if run is None:
            return MethodWorkspaceView("Desk Research", WorkspaceMethodState.NOT_STARTED,
                "Not started", "Add a research brief to begin Desk Research.", None,
                MethodOutputAvailabilityView(), WorkspaceActionView("Start Desk Research", f"/ui/projects/{project_id}/desk/new"))
        status = run.status.value
        total = len(run.tasks)
        complete = sum(task.status in {TaskStatus.COMPLETED, TaskStatus.SKIPPED} for task in run.tasks)
        progress = round(complete * 100 / total) if total else None
        state = WorkspaceMethodState.RUNNING
        label = "In progress"
        explanation = "Desk Research is working through the approved brief."
        if status == "paused": state, label, explanation = WorkspaceMethodState.ATTENTION, "Needs attention", "Desk Research is paused and needs attention."
        elif status == "completed": state, label, explanation = WorkspaceMethodState.COMPLETED, "Completed", "Desk Research completed and its supported outputs are available."
        elif status in {"failed", "cancelled"}: state, label, explanation = WorkspaceMethodState.LIMITED, "Limited", "Desk Research ended without a complete supported result."
        output = MethodOutputAvailabilityView()
        try:
            payload = self.research_results.get_detail_for_run(run.id).to_dict()
            detail = payload.get("detail", payload)
            output = MethodOutputAvailabilityView(
                findings_count=len(detail.get("findings", ())),
                insights_count=len(detail.get("insights", ())),
                report_available=bool(detail.get("report")),
                review_available=bool(detail.get("review")),
            )
        except Exception:
            pass
        open_action = WorkspaceActionView("Open Desk Research", f"/ui/research/{run.id}")
        return MethodWorkspaceView("Desk Research", state, label, explanation, progress, output,
                                   open_action, open_action)

    def _quant(self, project_id, study, run):
        if study is None:
            return MethodWorkspaceView("Quantitative Research", WorkspaceMethodState.NOT_STARTED,
                "Not started", "Create a quantitative study when a dataset-led method is needed.", None,
                MethodOutputAvailabilityView(), WorkspaceActionView("Start Quantitative Research", f"/ui/projects/{project_id}/quantitative/new"))
        state_value = study.state
        state, label, explanation = WorkspaceMethodState.READY, "Ready for setup", "Upload and review a dataset to continue."
        if run and run.status.value == "running": state, label, explanation = WorkspaceMethodState.RUNNING, "In progress", "Quantitative analysis is running."
        elif state_value in {"AWAITING_QC_APPROVAL", "AWAITING_WEIGHT_APPROVAL"}: state, label, explanation = WorkspaceMethodState.ATTENTION, "Needs attention", "A methodological review or approval is required."
        elif state_value == "COMPLETED": state, label, explanation = WorkspaceMethodState.COMPLETED, "Completed", "Quantitative analysis completed with supported outputs."
        elif state_value.startswith("COMPLETED_WITH"):
            state, label, explanation = WorkspaceMethodState.LIMITED, "Completed with limitations", "Analysis completed; a supported report or insight was not formed."
        elif run and run.status.value in {"failed", "cancelled"}: state, label, explanation = WorkspaceMethodState.LIMITED, "Limited", "The study ended without a complete supported result."
        output = MethodOutputAvailabilityView()
        try:
            view = self.quantitative and __import__("application.query.quantitative_study_query_service", fromlist=["QuantitativeStudyQueryService"]).QuantitativeStudyQueryService(ui_service=self.quantitative).get(study.study_id, owner_id=self.projects.get_project(project_id).owner_principal_id, active="overview")
            output = MethodOutputAvailabilityView(view.finding_count, view.insight_count,
                                                  view.analysis_count, bool(view.report_sections))
        except Exception:
            pass
        action = WorkspaceActionView("Open Quantitative Research", f"/ui/quantitative/studies/{study.study_id}/overview")
        return MethodWorkspaceView("Quantitative Research", state, label, explanation, None, output, action, action)

    @staticmethod
    def _humanize(value):
        return str(getattr(value, "value", value)).replace("_", " ").title()

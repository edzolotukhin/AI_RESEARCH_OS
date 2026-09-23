from __future__ import annotations

from application.query.project_workspace_views import (
    MethodOutputAvailabilityView, MethodWorkspaceView, ProjectBriefSummaryView,
    ProjectListItemView, ProjectListView, ProjectWorkspaceView,
    WorkspaceActionView, WorkspaceMethodState,
)
from application.quantitative.workflow import build_quantitative_workflow_template
from domain.value_objects.task_status import TaskStatus
from domain.research_method import DESK, QUANTITATIVE


class ProjectWorkspaceQueryService:
    def __init__(self, *, project_service, workflow_service, quantitative_ui_service,
                 research_result_service, project_planning_service) -> None:
        self.projects = project_service
        self.workflows = workflow_service
        self.quantitative = quantitative_ui_service
        self.research_results = research_result_service
        self.planning = project_planning_service

    def list(self, *, owner_id: str) -> ProjectListView:
        items = []
        for project in self.projects.list_projects(owner_principal_id=owner_id):
            view = self.get(project.id, owner_id=owner_id)
            items.append(ProjectListItemView(
                project.id, project.name, self._humanize(project.status),
                tuple((method.name, method.state_label) for method in view.methods),
                bool(view.attention_items),
            ))
        return ProjectListView(tuple(items))

    def get(self, project_id: str, *, owner_id: str) -> ProjectWorkspaceView:
        project = self.projects.get_project(project_id)
        if project.owner_principal_id != owner_id:
            from application.persistence.exceptions import AccessDeniedError
            raise AccessDeniedError(f"Проєкт не знайдено: {project_id}")
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
        selected = self.planning.explicit_or_inferred_methods(project)
        desk = self._desk(project_id, desk_run, project) if DESK in selected else None
        quant = self._quant(project_id, quant_study, quant_run, project) if QUANTITATIVE in selected else None
        methods = tuple(item for item in (desk, quant) if item is not None)
        brief = None if project.research_brief is None else ProjectBriefSummaryView(
            project.research_brief.title, project.research_brief.business_question,
            project.research_brief.objectives,
        )
        attention = tuple(x.name for x in methods if x.state is WorkspaceMethodState.ATTENTION)
        return ProjectWorkspaceView(project.id, project.name, self._humanize(project.status),
                                    brief, desk, quant, methods,
                                    self.planning.available_methods(project),
                                    project.research_design_status,
                                    self.planning.design_is_current(project),
                                    attention)

    @staticmethod
    def _study_type():
        from domain.quantitative.workflow import QuantitativeStudyProjection
        return QuantitativeStudyProjection

    def _desk(self, project_id, run, project):
        if run is None:
            approved = project.research_design_status == "APPROVED" and self.planning.design_is_current(project)
            return MethodWorkspaceView("Кабінетне дослідження", WorkspaceMethodState.READY if approved else WorkspaceMethodState.NOT_STARTED,
                "Готове до запуску" if approved else "Очікує затвердження дизайну",
                "Дизайн затверджено; метод можна активувати." if approved else "Збережіть бриф, сформуйте та затвердьте дизайн дослідження.", None,
                MethodOutputAvailabilityView(), WorkspaceActionView(
                    "Розпочати кабінетне дослідження" if approved else "Перейти до дизайну",
                    f"/ui/projects/{project_id}/methods/DESK/activate" if approved else f"/ui/projects/{project_id}/design"))
        status = run.status.value
        total = len(run.tasks)
        complete = sum(task.status in {TaskStatus.COMPLETED, TaskStatus.SKIPPED} for task in run.tasks)
        progress = round(complete * 100 / total) if total else None
        state = WorkspaceMethodState.RUNNING
        label = "Виконується"
        explanation = "Кабінетне дослідження виконується за визначеним брифом."
        if status == "paused": state, label, explanation = WorkspaceMethodState.ATTENTION, "Потребує уваги", "Кабінетне дослідження призупинено та потребує уваги."
        elif status == "completed": state, label, explanation = WorkspaceMethodState.COMPLETED, "Завершено", "Кабінетне дослідження завершено; підтримані результати доступні."
        elif status in {"failed", "cancelled"}: state, label, explanation = WorkspaceMethodState.LIMITED, "Завершено з обмеженнями", "Кабінетне дослідження завершилося без повного підтриманого результату."
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
        open_action = WorkspaceActionView("Відкрити кабінетне дослідження", f"/ui/research/{run.id}/overview")
        return MethodWorkspaceView("Кабінетне дослідження", state, label, explanation, progress, output,
                                   open_action, open_action)

    def _quant(self, project_id, study, run, project):
        if study is None:
            approved = project.research_design_status == "APPROVED" and self.planning.design_is_current(project)
            return MethodWorkspaceView("Кількісне дослідження", WorkspaceMethodState.READY if approved else WorkspaceMethodState.NOT_STARTED,
                "Готове до налаштування" if approved else "Очікує затвердження дизайну",
                "Дизайн затверджено; метод можна налаштувати." if approved else "Збережіть бриф, сформуйте та затвердьте дизайн дослідження.", None,
                MethodOutputAvailabilityView(), WorkspaceActionView(
                    "Налаштувати кількісне дослідження" if approved else "Перейти до дизайну",
                    f"/ui/projects/{project_id}/methods/QUANTITATIVE/activate" if approved else f"/ui/projects/{project_id}/design"))
        state_value = study.state
        state, label, explanation = WorkspaceMethodState.READY, "Готове до налаштування", "Завантажте та перевірте набір даних, щоб продовжити."
        if run and run.status.value == "running": state, label, explanation = WorkspaceMethodState.RUNNING, "Виконується", "Виконується кількісний аналіз даних."
        elif state_value in {"AWAITING_QC_APPROVAL", "AWAITING_WEIGHT_APPROVAL"}: state, label, explanation = WorkspaceMethodState.ATTENTION, "Потребує уваги", "Потрібна методологічна перевірка або підтвердження."
        elif state_value == "COMPLETED": state, label, explanation = WorkspaceMethodState.COMPLETED, "Завершено", "Кількісний аналіз завершено; підтримані результати доступні."
        elif state_value.startswith("COMPLETED_WITH"):
            state, label, explanation = WorkspaceMethodState.LIMITED, "Завершено з обмеженнями", "Аналіз завершено; підтриманий звіт або інсайт не сформовано."
        elif run and run.status.value in {"failed", "cancelled"}: state, label, explanation = WorkspaceMethodState.LIMITED, "Завершено з обмеженнями", "Дослідження завершилося без повного підтриманого результату."
        output = MethodOutputAvailabilityView()
        try:
            view = self.quantitative and __import__("application.query.quantitative_study_query_service", fromlist=["QuantitativeStudyQueryService"]).QuantitativeStudyQueryService(ui_service=self.quantitative).get(study.study_id, owner_id=self.projects.get_project(project_id).owner_principal_id, active="overview")
            output = MethodOutputAvailabilityView(view.finding_count, view.insight_count,
                                                  view.analysis_count, bool(view.report_sections))
        except Exception:
            pass
        action = WorkspaceActionView("Відкрити кількісне дослідження", f"/ui/quantitative/studies/{study.study_id}/overview")
        return MethodWorkspaceView("Кількісне дослідження", state, label, explanation, None, output, action, action)

    @staticmethod
    def _humanize(value):
        key = str(getattr(value, "value", value)).casefold()
        return {
            "lead": "Новий",
            "research design": "Дизайн дослідження",
            "client approval": "Очікує підтвердження",
            "approved": "Підтверджено",
            "project setup": "Налаштування проєкту",
            "data processing": "Обробка даних",
            "reporting": "Підготовка звіту",
            "fieldwork": "Польовий етап",
            "closed": "Завершено",
            "archived": "В архіві",
        }.get(key, "Стан не визначено")

from __future__ import annotations

from application.query.project_workspace_views import (
    MethodOutputAvailabilityView, MethodWorkspaceView, ProjectBriefSummaryView,
    ProjectListItemView, ProjectListView, ProjectWorkspaceView,
    WorkspaceActionView, WorkspaceMethodState, WorkspaceRunView,
)
from application.query.research_outcome_presentation import present_research_outcome, readiness_reasons
from application.query.research_run_result import ResearchRunResultProjectionError
from application.research_quality.readiness_result_codec import extract_research_readiness, extract_research_product_outcome
from application.quantitative.workflow import build_quantitative_workflow_template
from domain.value_objects.task_status import TaskStatus
from domain.research_method import DESK, QUANTITATIVE, QUALITATIVE
from application.qualitative.service import QUAL_TEMPLATE
from application.workflow_kind import WorkflowKind, classify_workflow_template


class ProjectWorkspaceQueryService:
    def __init__(self, *, project_service, workflow_service, quantitative_ui_service,
                 research_result_service, project_planning_service, qualitative_service=None,
                 downstream_replay_service=None, deliverables_service=None) -> None:
        self.projects = project_service
        self.workflows = workflow_service
        self.quantitative = quantitative_ui_service
        self.research_results = research_result_service
        self.planning = project_planning_service
        self.qualitative = qualitative_service
        self.downstream_replay = downstream_replay_service
        self.deliverables = deliverables_service

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
            elif (
                run.workflow_template_id not in {quant_template_id, QUAL_TEMPLATE}
                and classify_workflow_template(
                    self.workflows.get_template(run.workflow_template_id)
                ) != WorkflowKind.PROJECT_DESIGN
            ):
                desk_runs.append(run)
        ordered_desk_runs = self.planning._order_desk_attempts(
            desk_runs, project_id,
        )
        desk_run = ordered_desk_runs[-1] if ordered_desk_runs else None
        selected = self.planning.explicit_or_inferred_methods(project)
        desk = self._desk(project_id, desk_run, project, owner_id) if DESK in selected else None
        quant = self._quant(project_id, quant_study, quant_run, project) if QUANTITATIVE in selected else None
        qual_run = next((run for run in runs if run.workflow_template_id == QUAL_TEMPLATE), None)
        qualitative = self._qual(project_id, qual_run, owner_id) if QUALITATIVE in selected else None
        methods = tuple(item for item in (desk, quant, qualitative) if item is not None)
        brief = None if project.research_brief is None else ProjectBriefSummaryView(
            project.research_brief.title, project.research_brief.business_question,
            project.research_brief.objectives,
        )
        attention = tuple(x.name for x in methods if x.state is WorkspaceMethodState.ATTENTION)
        can_regenerate, regeneration_reason = (
            self.planning.design_regeneration_eligibility(project)
        )
        return ProjectWorkspaceView(
            project_id=project.id, project_name=project.name,
            lifecycle=self._humanize(project.status), brief=brief,
            desk=desk, quantitative=quant, qualitative=qualitative,
            methods=methods,
            available_methods=self.planning.available_methods(project),
            design_status=project.research_design_status,
            design_current=self.planning.design_is_current(project),
            attention_items=attention,
            can_regenerate_design=can_regenerate,
            design_regeneration_block_reason=regeneration_reason,
            desk_history=tuple(WorkspaceRunView(run.id,
                desk.state_label if desk and run.id == desk.run_id else present_research_outcome(run.status.value, self._desk_outcome(run)).label,
                f"/ui/research/{run.id}/overview", run.id == (desk.run_id if desk else None))
                for run in reversed(ordered_desk_runs)) if desk else (),
        )

    @staticmethod
    def _study_type():
        from domain.quantitative.workflow import QuantitativeStudyProjection
        return QuantitativeStudyProjection

    def _desk_outcome(self, run):
        if not run.is_terminal:
            return None
        try:
            return self.research_results.get_for_run(run.id).outcome.value
        except (ResearchRunResultProjectionError, ValueError):
            # Missing/conflicting historical outcome is not research success.
            return None

    def _desk(self, project_id, run, project, owner_id=None):
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
        outcome = self._desk_outcome(run)
        presentation = present_research_outcome(status, outcome)
        state = {"success": WorkspaceMethodState.COMPLETED, "running": WorkspaceMethodState.RUNNING,
                 "error": WorkspaceMethodState.ATTENTION, "neutral": WorkspaceMethodState.LIMITED}.get(
                     presentation.tone, WorkspaceMethodState.LIMITED if outcome == "PARTIAL" else WorkspaceMethodState.ATTENTION)
        label, explanation = presentation.label, presentation.explanation
        # This percentage describes execution only, never research sufficiency.
        if status == "completed" and outcome not in {"COMPLETED", "APPROVED"}:
            progress = None
        output = MethodOutputAvailabilityView()
        try:
            output = MethodOutputAvailabilityView(**self.research_results.available_outputs_for_run(run.id))
        except Exception:
            pass
        if self.deliverables is not None and owner_id is not None:
            try:
                from dataclasses import replace
                catalog = self.deliverables.catalog(project_id, owner_id=owner_id)
                items = [item for item in catalog.desk if item.document.run_id == run.id]
                output = replace(output, pdf_available=any(item.pdf is not None for item in items),
                                 pptx_available=any(item.pptx is not None for item in items))
            except Exception:
                pass  # Unavailable file metadata cannot promote the outcome.
        task_results = self.workflows.get_task_results(run.id)
        try:
            product = extract_research_product_outcome(task_results) or {}
        except ValueError:
            product = {}
        reasons = readiness_reasons(extract_research_readiness(task_results),
            self.workflows.get_template(run.workflow_template_id).research_design_snapshot,
            missing_ids=product.get("unresolved_information_need_ids", ())) if run.is_terminal else ()
        open_action = WorkspaceActionView("Відкрити кабінетне дослідження", f"/ui/research/{run.id}/overview")
        primary_action = open_action
        if status in {"completed", "failed", "cancelled"}:
            explanation += " Попередній запуск буде збережено; новий запуск не замінить його результати."
            primary_action = WorkspaceActionView(
                "Запустити нове дослідження",
                f"/ui/projects/{project_id}/methods/DESK/retry",
            )
        replay_action = None
        if run is not None and owner_id is not None and self.downstream_replay is not None:
            source_id = self.downstream_replay.reusable_source_run_id(
                project_id=project_id, run_id=run.id, owner_id=owner_id,
            )
            if source_id is not None:
                replay_action = WorkspaceActionView(
                    "Повторити фіналізацію",
                    f"/ui/projects/{project_id}/methods/DESK/{source_id}/finalization-replay",
                )
        return MethodWorkspaceView("Кабінетне дослідження", state, label, explanation, progress, output,
                                   primary_action, open_action,
                                   run_id=run.id,
                                   execution_status=(
                                       "TERMINAL"
                                       if run.is_terminal else "RUNNING"
                                   ), replay_action=replay_action, research_outcome=outcome,
                                   insufficiency_reasons=reasons)

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

    def _qual(self, project_id, run, owner_id):
        if run is None:
            return MethodWorkspaceView("Глибинні інтерв’ю", WorkspaceMethodState.READY,
                "Готове до налаштування", "Додайте аудіо або готовий транскрипт.", None,
                MethodOutputAvailabilityView(), WorkspaceActionView("Налаштувати глибинні інтерв’ю",
                f"/ui/projects/{project_id}/methods/QUALITATIVE/activate"))
        readiness = self.qualitative.readiness(project_id, run.id, owner_id=owner_id).value
        ready = readiness == "authority_ready_for_coding"
        action = WorkspaceActionView("Відкрити глибинні інтерв’ю", f"/ui/projects/{project_id}/qualitative/{run.id}")
        return MethodWorkspaceView("Глибинні інтерв’ю", WorkspaceMethodState.READY if ready else WorkspaceMethodState.RUNNING,
            "Готове до майбутнього кодування" if ready else "Підготовка транскрипту",
            "Канонічний транскрипт готовий; аналіз ще не виконувався." if ready else "Завершіть канонічний транскрипт.",
            None, MethodOutputAvailabilityView(), action, action)

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

"""Project navigation over independent, canonical method output read models."""

from __future__ import annotations

from dataclasses import dataclass

from application.persistence.exceptions import AccessDeniedError
from application.query.desk_workbench_query_service import DeskWorkbenchQueryService
from application.query.quantitative_study_query_service import QuantitativeStudyQueryService
from application.quantitative.workflow import build_quantitative_workflow_template
from domain.quantitative.workflow import QuantitativeStudyProjection
from domain.research_method import DESK, QUANTITATIVE


@dataclass(frozen=True)
class MethodOutputsView:
    name: str
    state: str
    tone: str
    explanation: str
    outputs: tuple[str, ...]
    report: str
    href: str | None


@dataclass(frozen=True)
class ProjectOutputsView:
    project_id: str
    project_name: str
    methods: tuple[MethodOutputsView, ...]


class ProjectOutputsQueryService:
    def __init__(self, *, container) -> None:
        self.container = container

    def get(self, project, *, owner_id: str) -> ProjectOutputsView:
        # Defense in depth: ownership precedes all method-run and output reads.
        if project.owner_principal_id != owner_id:
            raise AccessDeniedError("Проєкт не знайдено")
        methods = self.container.project_planning_service.explicit_or_inferred_methods(project)
        runs = self.container.workflow_service.list_workflow_runs_for_project(project.id)
        quant_template_id = build_quantitative_workflow_template().id
        desk_runs = []
        quant_matches = []
        for run in runs:
            if run.project_id != project.id:
                raise AccessDeniedError("Некоректний зв’язок проєкту та дослідження")
            snapshots = self.container.quantitative_ui_service.state.list_for_run(
                run.id, project_id=project.id, expected_type=QuantitativeStudyProjection,
            )
            if snapshots:
                if run.workflow_template_id != quant_template_id:
                    raise ValueError("Quantitative study has an unexpected workflow template")
                quant_matches.append((run, max(snapshots, key=lambda item: item.revision)))
            elif run.workflow_template_id != quant_template_id:
                desk_runs.append(run)

        result = []
        if DESK in methods:
            result.append(self._desk(project, desk_runs[-1] if desk_runs else None))
        if QUANTITATIVE in methods:
            result.append(self._quant(project, owner_id, quant_matches[-1] if quant_matches else None))
        return ProjectOutputsView(project.id, project.name, tuple(result))

    def _desk(self, project, run) -> MethodOutputsView:
        name = "Кабінетне дослідження"
        if run is None:
            return MethodOutputsView(name, "Не активовано", "inactive",
                                     "Метод обрано, але дослідження ще не запущено.", (), "Звіт недоступний", None)
        detail = DeskWorkbenchQueryService(container=self.container).get(run.id, project=project)
        if detail.header.project_id != project.id or detail.header.run_id != run.id:
            raise AccessDeniedError("Некоректний зв’язок проєкту та дослідження")
        outputs = tuple(
            label for available, label in (
                (detail.sources_total > 0, "Джерела"),
                (detail.evidence_total > 0, "Докази"),
                (detail.findings_total > 0, "Висновки"),
                (detail.insights_total > 0, "Інсайти"),
            ) if available
        )
        report = "Звіт доступний" if detail.report.available else "Звіт недоступний"
        if detail.report.review is not None:
            report += f" · Перевірка: {detail.report.review.verdict}"
        return MethodOutputsView(name, detail.header.state, detail.header.state_tone,
                                 detail.header.activity, outputs, report,
                                 f"/ui/research/{run.id}/overview")

    def _quant(self, project, owner_id: str, match) -> MethodOutputsView:
        name = "Кількісне дослідження"
        if match is None:
            return MethodOutputsView(name, "Не активовано", "inactive",
                                     "Метод обрано, але дослідження ще не створено.", (), "Звіт недоступний", None)
        run, study = match
        if study.project_id != project.id or study.run_id != run.id:
            raise AccessDeniedError("Некоректний зв’язок проєкту та дослідження")
        view = QuantitativeStudyQueryService(ui_service=self.container.quantitative_ui_service).get(
            study.study_id, owner_id=owner_id, active="overview",
        )
        if view.project_id != project.id or view.study_id != study.study_id:
            raise AccessDeniedError("Некоректний зв’язок проєкту та дослідження")
        outputs = tuple(
            label for available, label in (
                (view.result_count > 0, "Статистичні результати"),
                (view.finding_count > 0, "Висновки"),
                (view.insight_count > 0, "Інсайти"),
            ) if available
        )
        report = "Звіт доступний" if view.report_sections else "Звіт недоступний"
        status = run.status.value
        if status in {"failed", "cancelled"} or study.state == "FAILED":
            state, tone = "Завершено з обмеженнями", "attention"
        elif status == "completed" or study.state == "COMPLETED":
            state, tone = "Завершено", "success"
        elif study.state.startswith("COMPLETED_WITH"):
            state, tone = "Завершено з обмеженнями", "attention"
        elif study.state == "WAITING_FOR_DATASET":
            state, tone = "Очікує даних", "inactive"
        elif study.state in {"AWAITING_QC_APPROVAL", "AWAITING_WEIGHT_APPROVAL"}:
            state, tone = "Потребує підтвердження", "attention"
        elif status == "running" or study.state == "ANALYZING":
            state, tone = "Виконується", "active"
        elif status == "paused":
            state, tone = "Потребує уваги", "attention"
        else:
            state, tone = "Очікує даних або налаштування", "inactive"
        return MethodOutputsView(name, state, tone,
                                 "Перегляньте стан і результати у кількісному дослідженні.",
                                 outputs, report,
                                 f"/ui/quantitative/studies/{study.study_id}/overview")

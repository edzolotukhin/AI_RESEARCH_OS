"""Project navigation over independent, canonical method output read models."""

from __future__ import annotations

from dataclasses import dataclass
from application.query.project_activity_views import ActivityTimeline

from application.persistence.exceptions import AccessDeniedError
from application.query.desk_workbench_query_service import DeskWorkbenchQueryService
from application.query.quantitative_study_query_service import QuantitativeStudyQueryService
from application.quantitative.workflow import (
    CMF_QUANTITATIVE_WORKFLOW_ID,
    QUANTITATIVE_WORKFLOW_ID,
)
from domain.quantitative.workflow import QuantitativeStudyProjection
from domain.research_method import DESK, QUANTITATIVE, QUALITATIVE
from application.qualitative.service import QUAL_TEMPLATE


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
    activity: ActivityTimeline = ActivityTimeline(state="unavailable")


class ProjectOutputsQueryService:
    def __init__(self, *, container) -> None:
        self.container = container

    def get(self, project, *, owner_id: str) -> ProjectOutputsView:
        # Defense in depth: ownership precedes all method-run and output reads.
        if project.owner_principal_id != owner_id:
            raise AccessDeniedError("Проєкт не знайдено")
        methods = self.container.project_planning_service.explicit_or_inferred_methods(project)
        runs = self.container.workflow_service.list_workflow_runs_for_project(project.id)
        quant_template_ids = {QUANTITATIVE_WORKFLOW_ID, CMF_QUANTITATIVE_WORKFLOW_ID}
        desk_runs = []
        quant_matches = []
        for run in runs:
            if run.project_id != project.id:
                raise AccessDeniedError("Некоректний зв’язок проєкту та дослідження")
            snapshots = self.container.quantitative_ui_service.state.list_for_run(
                run.id, project_id=project.id, expected_type=QuantitativeStudyProjection,
            )
            if snapshots:
                if run.workflow_template_id not in quant_template_ids:
                    raise ValueError("Quantitative study has an unexpected workflow template")
                quant_matches.append((run, max(snapshots, key=lambda item: item.revision)))
            elif run.workflow_template_id not in quant_template_ids | {QUAL_TEMPLATE}:
                desk_runs.append(run)

        result = []
        if DESK in methods:
            result.append(self._desk(project, desk_runs[-1] if desk_runs else None))
        if QUANTITATIVE in methods:
            result.append(self._quant(project, owner_id, quant_matches[-1] if quant_matches else None))
        if QUALITATIVE in methods:
            qual_run = next((run for run in runs if run.workflow_template_id == QUAL_TEMPLATE), None)
            result.append(self._qual(project, owner_id, qual_run))
        activity = ActivityTimeline(state="unavailable")
        reader = getattr(self.container, "activity_reader", None)
        if reader is not None:
            try:
                activity = reader.list_for_project(project.id)
            except Exception:
                activity = ActivityTimeline(state="error")
        return ProjectOutputsView(project.id, project.name, tuple(result), activity)

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

    def _qual(self, project, owner_id, run):
        if run is None:
            return MethodOutputsView("Глибинні інтерв’ю", "Не активовано", "inactive",
                "Метод обрано, але сесію ще не створено.", (), "Фінальний звіт недоступний", None)
        records = self.container.qualitative_service.records(project.id, run.id, owner_id=owner_id)
        transcripts = [x for x in records if x.record_type == "transcript"]
        exports = [x for x in records if x.record_type == "export"]
        codebooks = [x for x in records if x.record_type == "codebook_revision" and x.payload.get("status") == "accepted"]
        codings = [x for x in records if x.record_type == "coding_revision" and x.payload.get("status") == "accepted"]
        themes = [x for x in records if x.record_type == "thematic_revision" and x.payload.get("status") == "accepted"]
        findings = [x for x in records if x.record_type == "qualitative_finding" and x.payload.get("status") == "accepted"]
        insights = [x for x in records if x.record_type == "qualitative_insight" and x.payload.get("status") == "accepted"]
        approved = [x for x in records if x.record_type == "qualitative_approved_revision"]
        outputs = tuple(x for available, x in ((bool(transcripts), "Канонічний транскрипт"),
                                                (bool(exports), "DOCX транскрипту"),
                                                (bool(codebooks), "Прийнятий кодбук"),
                                                (bool(codings), "Прийняте кодування"),
                                                (bool(themes), "Прийнятий тематичний аналіз"),
                                                (bool(findings), "Прийняті якісні висновки"),
                                                (bool(insights), "Прийняті якісні інсайти"),
                                                (bool(approved), "Затверджена якісна версія")) if available)
        return MethodOutputsView("Глибинні інтерв’ю", "Готово до документів" if approved else ("Готово до висновків" if themes else ("Транскрипт готовий" if transcripts else "Підготовка")),
            "success" if transcripts else "active", "Тематичний аналіз є аналітичним authority, а не фінальним звітом.",
            outputs, "Фінальний звіт недоступний", f"/ui/projects/{project.id}/qualitative/{run.id}")

"""Read-only projection from canonical Quantitative state into UI-safe DTOs."""
from __future__ import annotations

from decimal import Decimal

from api.ui.quantitative_presentation import (
    canonical_value,
    finding_statement,
    format_base,
    format_statistic,
    humanize,
    present_quantitative_status,
)
from application.query.quantitative_study_views import (
    AnalysisItemView,
    FindingView,
    InsightView,
    MetricView,
    NavigationItemView,
    QuantitativeStudyView,
    ReportSectionView,
    ResultItemView,
    VariableView,
)
from domain.quantitative.analysis import StatisticalResult
from domain.quantitative.analysis_plan import QuantitativeAnalysisPlanVersion
from domain.quantitative.dataset import CodebookVersion, DatasetVersion
from domain.quantitative.finding import QuantitativeFindingGenerationResult
from domain.quantitative.insight import QuantitativeInsightGenerationResult
from domain.quantitative.quality import QualityControlRun
from domain.quantitative.questionnaire_authority import QuantitativeQuestionnaireVersion
from domain.quantitative.report import QuantitativeReportCompositionResult
from domain.quantitative.research_design_authority import QuantitativeResearchDesignVersion
from domain.quantitative.workflow import QuantitativeTerminalResult


def _value(value, fallback="—"):
    return canonical_value(value, fallback)


class QuantitativeStudyQueryService:
    def __init__(self, *, ui_service):
        self._ui = ui_service

    def get(self, study_id: str, *, owner_id: str, active: str) -> QuantitativeStudyView:
        study = self._ui.get(study_id, owner_id=owner_id)
        run = self._ui.workflows.get_workflow_run(study.run_id)
        records = tuple(self._ui.state.list_for_run(study.run_id, project_id=study.project_id))
        dataset = self._load(study.dataset_record_id, study.project_id, DatasetVersion)
        codebook = self._load(study.codebook_record_id, study.project_id, CodebookVersion)
        design = self._latest(records, QuantitativeResearchDesignVersion)
        questionnaire = self._latest(records, QuantitativeQuestionnaireVersion)
        plan = self._latest(records, QuantitativeAnalysisPlanVersion)
        qc = self._load(study.qc_record_id, study.project_id, QualityControlRun)
        terminal = self._latest(records, QuantitativeTerminalResult)
        stats = tuple(item for item in records if isinstance(item, StatisticalResult))
        finding_result = self._latest(records, QuantitativeFindingGenerationResult)
        insight_result = self._latest(records, QuantitativeInsightGenerationResult)
        report_result = self._latest(records, QuantitativeReportCompositionResult)

        terminal_name = _value(getattr(terminal, "terminal_outcome", ""), "")
        status = present_quantitative_status(run.status.value, terminal_outcome=terminal_name)
        report_status = present_quantitative_status(run.status.value, terminal_outcome=terminal_name, scope="report")
        base = f"/ui/quantitative/studies/{study.study_id}"
        navigation = tuple(
            NavigationItemView(key, label, f"{base}/{key}", key == active)
            for key, label in (("overview", "Огляд"), ("data", "Дані"), ("analysis", "Аналіз"), ("results", "Результати"), ("report", "Звіт"))
        )

        questions = tuple(_value(getattr(item, "statement", None)) for item in getattr(design, "research_questions", ()))
        target = getattr(design, "target_population", None)
        eligibility = tuple(getattr(target, "eligibility", ()))
        population = "; ".join(eligibility) if eligibility else "Не вказано"
        geography = ", ".join(getattr(target, "geography", ())) or "Не вказано"
        weighting = humanize(
            getattr(terminal, "weighting_mode", getattr(getattr(design, "methodology_intent", None), "weighting_intent", None)),
            "Не визначено",
        )
        variables = tuple(
            VariableView(
                item.name,
                item.label or "Без підпису",
                humanize(item.variable_type),
                humanize(item.role),
                humanize(item.measurement_level),
                ", ".join(humanize(rule.value if rule.value is not None else rule.kind) for rule in item.missing_rules) or "Не задекларовано",
            )
            for item in getattr(codebook, "variables", ())
        )

        result_counts: dict[str, int] = {}
        for item in stats:
            result_counts[item.analysis_specification_id] = result_counts.get(item.analysis_specification_id, 0) + 1
        analyses = tuple(
            AnalysisItemView(
                humanize(getattr(item.specification, "statistic_family", item.expected_result_family)),
                present_quantitative_status("completed" if result_counts.get(item.specification.specification_id) else "ready"),
                item.population_description or population,
                humanize(item.weighting_policy),
                result_counts.get(item.specification.specification_id, 0),
                tuple(item.limitations),
            )
            for item in getattr(plan, "planned_analyses", ())
        )
        results = tuple(self._result_view(item, population) for item in stats)
        findings = tuple(self._finding_view(item) for item in getattr(finding_result, "accepted_findings", ()))
        insights = tuple(InsightView(item.insight_text, len(item.supporting_finding_refs)) for item in getattr(insight_result, "accepted_insights", ()))
        report = getattr(report_result, "accepted_report", None)
        sections = tuple(ReportSectionView(item.title, item.narrative) for item in getattr(report, "sections", ()))
        limitations = tuple(dict.fromkeys((*getattr(design, "limitations", ()), *getattr(plan, "limitations", ()), *getattr(terminal, "limitations", ()))))
        warnings = tuple(dict.fromkeys((*getattr(dataset, "warnings", ()), *(getattr(item, "message", _value(item)) for item in getattr(qc, "issues", ())))))
        analytical_requirement_count = len(getattr(design, "analytical_requirements", ()))
        metrics = (
            MetricView("Питання дослідження", str(len(questions)), "Затверджені питання", "purple"),
            MetricView("Аналітичні вимоги", str(analytical_requirement_count), "Покриття дизайну", "teal"),
            MetricView("Респонденти", str(dataset.row_count) if dataset else "—", "Без показу персональних даних"),
            MetricView("Результати", str(len(results)), f"{len(findings)} підтверджених висновків", "green"),
        )

        taskmap = {task.definition_id: task for task in run.tasks}
        def stage(label, definition, href):
            task = taskmap.get(definition)
            if definition == "quant_report" and report is None:
                return (label, report_status, href)
            return (label, present_quantitative_status(task.status.value if task else "waiting"), href)
        stages = (
            stage("Дизайн дослідження", "quant_research_design", f"{base}/overview"),
            stage("Анкета", "quant_questionnaire", f"{base}/overview"),
            stage("Дані", "quant_import", f"{base}/data"),
            stage("Аналіз", "quant_analysis", f"{base}/analysis"),
            stage("Результати", "quant_findings", f"{base}/results"),
            stage("Звіт", "quant_report", f"{base}/report"),
        )
        return QuantitativeStudyView(
            study.study_id, study.title, study.description, run.status.value, status,
            navigation, metrics, stages, questions, analytical_requirement_count,
            humanize(getattr(design, "methodology", None), "Кількісне дослідження"), population, geography, weighting,
            _value(getattr(dataset, "original_filename", None), "Дані ще не завантажено"),
            humanize(getattr(dataset, "format", None)), getattr(dataset, "row_count", None), getattr(dataset, "variable_count", None),
            humanize(getattr(dataset, "validation_status", None)), variables, len(getattr(qc, "issues", ())),
            analyses, results, findings, insights, _value(getattr(report, "title", None), "Автоматичний звіт"), sections,
            report_status, limitations, warnings, run.status.value == "paused", study.state == "IMPORTED",
            run.status.value == "paused" and study.state == "READY_TO_ANALYZE",
            sum(1 for item in analyses if item.result_count), len(results), len(findings), len(insights),
            study.project_id,
        )

    @staticmethod
    def _result_view(result, population: str) -> ResultItemView:
        raw = Decimal(str(result.value))
        percentage = "PERCENTAGE" in result.statistic_type
        return ResultItemView(
            result.variable_id,
            humanize(result.statistic_type),
            format_statistic(result.value, result.statistic_type),
            _value(result.numerator),
            format_base(result.denominator),
            population,
            humanize(result.base_definition),
            humanize(result.filter_definition),
            humanize(result.weighting_status),
            ", ".join(map(str, result.grouped_category_members)),
            str(max(Decimal(0), min(Decimal(100), raw))) if percentage else "0",
        )

    @staticmethod
    def _finding_view(finding) -> FindingView:
        context = finding.semantic_evidence_context
        if context is None:
            return FindingView(finding_statement(finding.text), len(finding.statistical_result_refs), humanize(finding.support_validation_status))
        return FindingView(
            finding_statement(finding.text), len(finding.statistical_result_refs), humanize(finding.support_validation_status),
            format_statistic(context.value, context.statistic_type), context.question_context, context.population_description or "Не вказано",
            humanize(context.base_definition), format_base(context.denominator), humanize(context.weighting_status), context.category_label,
        )

    def _load(self, record_id, project_id, kind):
        return self._ui.state.load(record_id, project_id=project_id, expected_type=kind) if record_id else None

    @staticmethod
    def _latest(records, kind):
        values = [item for item in records if isinstance(item, kind)]
        return values[-1] if values else None

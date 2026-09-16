"""Read-only projection from canonical Quantitative state into UI-safe DTOs."""
from __future__ import annotations
from enum import Enum
from application.query.quantitative_study_views import *
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
    if value is None or value == "": return fallback
    return str(value.value if isinstance(value, Enum) else value)

def present_quantitative_status(workflow_status: str, *, terminal_outcome: str = "", scope: str = "study") -> ProductStatusView:
    terminal = terminal_outcome.upper()
    if terminal == "COMPLETED_WITH_NO_SUPPORTED_FINDINGS":
        return ProductStatusView("insufficient", "Недостатньо даних", "warning", "Підтверджених висновків недостатньо.")
    if terminal == "COMPLETED_WITH_NO_SUPPORTED_INSIGHTS":
        return ProductStatusView("partial", "Не сформовано" if scope == "report" else "Частково підтверджено", "warning", "Аналіз завершено, але міжрезультатні інсайти недостатньо підтверджені.")
    if terminal == "COMPLETED_WITH_NO_SUPPORTED_REPORT":
        return ProductStatusView("partial", "Не сформовано", "warning", "Підтриманого автоматичного звіту немає.")
    return {
        "created": ProductStatusView("waiting", "Очікує", "neutral"),
        "waiting": ProductStatusView("waiting", "Очікує", "neutral"),
        "ready": ProductStatusView("ready", "Готово до запуску", "info"),
        "running": ProductStatusView("running", "Виконується", "info"),
        "paused": ProductStatusView("review", "Готово до оцінки", "warning", "Доступна наступна підтверджена дія.", ("resume",)),
        "completed": ProductStatusView("complete", "Завершено", "success"),
        "skipped": ProductStatusView("skipped", "Не потрібно", "neutral"),
        "failed": ProductStatusView("attention", "Потребує уваги", "danger"),
        "cancelled": ProductStatusView("attention", "Потребує уваги", "danger"),
    }.get(workflow_status.lower(), ProductStatusView("unknown", "Очікує", "neutral"))

class QuantitativeStudyQueryService:
    def __init__(self, *, ui_service): self._ui = ui_service
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
        nav = tuple(NavigationItemView(k, l, f"{base}/{k}", k == active) for k,l in (("overview","Огляд"),("data","Дані"),("analysis","Аналіз"),("results","Результати"),("report","Звіт")))
        questions = tuple(_value(getattr(x, "statement", None)) for x in getattr(design, "research_questions", ()))
        pop = getattr(design, "target_population", None)
        eligibility = tuple(getattr(pop, "eligibility", ()))
        population = "; ".join(eligibility) if eligibility else "Не вказано"
        geography = ", ".join(getattr(pop, "geography", ())) or "Не вказано"
        weighting = _value(getattr(terminal, "weighting_mode", getattr(getattr(design,"methodology_intent",None),"weighting_intent",None)), "Не визначено")
        variables = tuple(VariableView(x.name, x.label or "Без підпису", _value(x.variable_type), _value(x.role), x.measurement_level, ", ".join(_value(r.value if r.value is not None else r.kind) for r in x.missing_rules) or "Не задекларовано") for x in getattr(codebook,"variables",()))
        result_counts = {}
        for x in stats: result_counts[x.analysis_specification_id] = result_counts.get(x.analysis_specification_id,0)+1
        analyses = tuple(AnalysisItemView(_value(getattr(x.specification,"statistic_family",x.expected_result_family)), present_quantitative_status("completed" if result_counts.get(x.specification.specification_id) else "ready"), x.population_description or population, _value(x.weighting_policy), result_counts.get(x.specification.specification_id,0), tuple(x.limitations)) for x in getattr(plan,"planned_analyses",()))
        results = tuple(ResultItemView(x.variable_id,x.statistic_type,_value(x.value),_value(x.numerator),_value(x.denominator),population,x.base_definition,x.filter_definition,x.weighting_status,", ".join(map(str,x.grouped_category_members))) for x in stats)
        findings = tuple(FindingView(x.text,len(x.statistical_result_refs),_value(x.support_validation_status)) for x in getattr(finding_result,"accepted_findings",()))
        insights = tuple(InsightView(x.insight_text,len(x.supporting_finding_refs)) for x in getattr(insight_result,"accepted_insights",()))
        report = getattr(report_result,"accepted_report",None)
        sections = tuple(ReportSectionView(x.title,x.narrative) for x in getattr(report,"sections",()))
        limitations = tuple(dict.fromkeys((*getattr(design,"limitations",()),*getattr(plan,"limitations",()),*getattr(terminal,"limitations",()))))
        warnings = tuple(dict.fromkeys((*getattr(dataset,"warnings",()),*(getattr(x,"message",_value(x)) for x in getattr(qc,"issues",())))))
        metrics=(MetricView("Питання дослідження",str(len(questions)),tone="purple"),MetricView("Питання анкети",str(len(getattr(questionnaire,"questions",()))),tone="teal"),MetricView("Респонденти",str(dataset.row_count) if dataset else "—"),MetricView("Результати",str(len(results)),tone="green"))
        taskmap={x.definition_id:x for x in run.tasks}
        def stage(label,definition,href):
            task=taskmap.get(definition); return (label,present_quantitative_status(task.status.value if task else "waiting"),href)
        stages=(stage("Дизайн дослідження","quant_research_design",f"{base}/overview"),stage("Анкета","quant_questionnaire",f"{base}/overview"),stage("Дані","quant_import",f"{base}/data"),stage("Аналіз","quant_analysis",f"{base}/analysis"),stage("Результати","quant_findings",f"{base}/results"),stage("Звіт","quant_report",f"{base}/report"))
        return QuantitativeStudyView(study.study_id,study.title,study.description,run.status.value,status,nav,metrics,stages,questions,len(getattr(design,"analytical_requirements",())),_value(getattr(design,"methodology",None),"Кількісне дослідження"),population,geography,weighting,_value(getattr(dataset,"original_filename",None),"Дані ще не завантажено"),_value(getattr(dataset,"format",None)),getattr(dataset,"row_count",None),getattr(dataset,"variable_count",None),_value(getattr(dataset,"validation_status",None)),variables,len(getattr(qc,"issues",())),analyses,results,findings,insights,_value(getattr(report,"title",None),"Автоматичний звіт"),sections,report_status,limitations,warnings,run.status.value=="paused",study.state=="IMPORTED",run.status.value=="paused" and study.state=="READY_TO_ANALYZE")
    def _load(self,record_id,project_id,kind):
        return self._ui.state.load(record_id,project_id=project_id,expected_type=kind) if record_id else None
    @staticmethod
    def _latest(records,kind):
        values=[x for x in records if isinstance(x,kind)]
        return values[-1] if values else None
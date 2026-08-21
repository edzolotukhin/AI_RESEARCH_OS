from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from application.quantitative.cross_tab_statistics import CrossTabStatisticsService
from application.quantitative.dataset_import_service import QuantitativeDatasetImportService, VariableOverride
from application.quantitative.finding_generation import QuantitativeFindingGenerationService
from application.quantitative.fingerprints import fingerprint_analysis_specification
from application.quantitative.insight_synthesis import QuantitativeInsightSynthesisService
from application.quantitative.kpi_statistics import KpiStatisticsService
from application.quantitative.numeric_statistics import NumericStatisticsService
from application.quantitative.one_way_statistics import OneWayStatisticsService
from application.quantitative.quality_control import (
    CleaningEngine, DataQualityService, assess_dataset_quality,
)
from application.quantitative.report_composition import QuantitativeReportCompositionService
from application.quantitative.state_persistence import QuantitativeStateService, authority_fingerprint
from application.quantitative.weighting import WeightImportService, approve_weight_set, build_analytical_view
from application.quantitative.target_margin_weighting import TargetMarginWeightingService
from application.quantitative.workflow import (
    QuantitativeApprovalRequired, QuantitativeApprovalService, QuantitativeWorkflowError,
)
from domain.quantitative.analysis import (
    AnalysisSpecification, CrossTabAnalysisSpecification,
    NpsAnalysisSpecification, NumericAnalysisSpecification, StatisticalResult,
)
from domain.quantitative.dataset import CodebookVersion, DatasetFormat, DatasetVersion
from domain.quantitative.finding import QuantitativeFindingGenerationResult
from domain.quantitative.insight import QuantitativeInsightGenerationResult
from domain.quantitative.quality import (
    CleaningDecisionSet, DatasetQualityState, QualityControlRun, QuestionnaireSnapshot,
)
from domain.quantitative.report import QuantitativeReportCompositionResult
from domain.quantitative.weighting import WeightSet, WeightSetApproval, WeightingMode, WeightingTargetPlan
from domain.quantitative.workflow import QuantitativeAnalysisManifest, QuantitativeTerminalOutcome, QuantitativeTerminalResult
from application.quantitative.fingerprints import canonical_digest


@dataclass(frozen=True)
class QuantitativeVerticalPlan:
    dataset_bytes: bytes
    filename: str
    dataset_id: str
    variable_overrides: Mapping[str, VariableOverride]
    questionnaire: QuestionnaireSnapshot
    imported_weight_rows: tuple[tuple[object, object], ...]
    weight_source_checksum: str
    one_way: AnalysisSpecification
    cross_tab: CrossTabAnalysisSpecification
    numeric: NumericAnalysisSpecification
    nps: NpsAnalysisSpecification
    cleaning_decision_set: CleaningDecisionSet | None = None
    weight_mode: str = "IMPORT_PRECOMPUTED_WEIGHTSET"
    weighting_target_plan: WeightingTargetPlan | None = None


class RealQuantitativeStageService:
    """Thin Q1-16 facade over QA-QK owners; it contains no analytical logic."""

    def __init__(
        self, *, plan: QuantitativeVerticalPlan, storage, digest_provider,
        state_service: QuantitativeStateService, approval_service: QuantitativeApprovalService,
        finding_service: QuantitativeFindingGenerationService,
        insight_service: QuantitativeInsightSynthesisService,
        report_service: QuantitativeReportCompositionService,
        importers: Sequence,
        generation_mode: str = "offline",
    ) -> None:
        self.plan, self.storage, self.digest = plan, storage, digest_provider
        self.state, self.approvals = state_service, approval_service
        self.findings, self.insights, self.reports = finding_service, insight_service, report_service
        self.generation_mode = generation_mode
        self.importer = QuantitativeDatasetImportService(importers=tuple(importers), storage=storage, digest_provider=digest_provider)
        self.qc = DataQualityService(storage=storage, digest_provider=digest_provider)
        self.cleaner = CleaningEngine(storage=storage, digest_provider=digest_provider)
        self.weights = WeightImportService(storage=storage, digest_provider=digest_provider)
        self.target_weights = TargetMarginWeightingService(storage=storage, digest_provider=digest_provider)
        self.one_way = OneWayStatisticsService(storage=storage, digest_provider=digest_provider)
        self.cross_tab = CrossTabStatisticsService(storage=storage, digest_provider=digest_provider)
        self.numeric = NumericStatisticsService(storage=storage, digest_provider=digest_provider)
        self.kpi = KpiStatisticsService(storage=storage, digest_provider=digest_provider)

    def execute_stage(self, stage_id: str, *, project_id: str, run_id: str, safe_state: Mapping[str, str]) -> Mapping[str, str]:
        handler = getattr(self, f"_{stage_id}", None)
        if handler is None: raise QuantitativeWorkflowError(f"unsupported Quantitative stage: {stage_id}")
        return handler(project_id, run_id, dict(safe_state))

    def _persist(self, value, kind, project_id, run_id, *, dataset_id=None, accepted=None):
        fp = authority_fingerprint(value)
        record_id = f"{run_id}:{kind}:{fp}"
        self.state.persist(value, record_id=record_id, project_id=project_id, run_id=run_id, dataset_version_id=dataset_id, accepted=accepted)
        return record_id

    def _load(self, state, key, project_id, expected):
        record_id = state.get(key)
        if not record_id: raise QuantitativeWorkflowError(f"missing authoritative workflow reference: {key}")
        return self.state.load(record_id, project_id=project_id, expected_type=expected)

    def _quant_import(self, project_id, run_id, state):
        imported = self.importer.import_bytes(self.plan.dataset_bytes, filename=self.plan.filename, dataset_format=DatasetFormat.SAV, dataset_id=self.plan.dataset_id, project_id=project_id, run_id=run_id, overrides=dict(self.plan.variable_overrides))
        state["dataset_record_id"] = self._persist(imported.dataset_version, "dataset", project_id, run_id, dataset_id=imported.dataset_version.version_id)
        state["codebook_record_id"] = self._persist(imported.codebook, "codebook", project_id, run_id, dataset_id=imported.dataset_version.version_id)
        state["dataset_version_id"], state["dataset_fingerprint"] = imported.dataset_version.version_id, imported.dataset_version.dataset_fingerprint
        return state

    def _quant_qc(self, project_id, run_id, state):
        dataset = self._load(state, "dataset_record_id", project_id, DatasetVersion); codebook = self._load(state, "codebook_record_id", project_id, CodebookVersion)
        qc = self.qc.detect(dataset=dataset, codebook=codebook, questionnaire=self.plan.questionnaire, detection_run_id=f"{run_id}:qc:{dataset.version_id}")
        state["qc_record_id"] = self._persist(qc, "qc", project_id, run_id, dataset_id=dataset.version_id)
        state["qc_fingerprint"] = qc.fingerprint
        return state

    def _quant_qc_approval(self, project_id, run_id, state):
        approval_id = state.get("qc_approval_id")
        if not approval_id: raise QuantitativeApprovalRequired(subject_type="QC", subject_id=state["qc_record_id"], subject_fingerprint=state["qc_fingerprint"])
        self.approvals.require_current(approval_id, project_id=project_id, subject_fingerprint=state["qc_fingerprint"])
        return state

    def _quant_cleaning(self, project_id, run_id, state):
        decision_set = self.plan.cleaning_decision_set
        if decision_set is None or not any(item.material for item in decision_set.decisions):
            state["cleaning_status"] = "NOT_REQUIRED"; return state
        if "cleaned_dataset_record_id" not in state:
            parent = self._load(state, "dataset_record_id", project_id, DatasetVersion); codebook = self._load(state, "codebook_record_id", project_id, CodebookVersion)
            child = self.cleaner.execute(parent=parent, codebook=codebook, decision_set=decision_set)
            if child is None: raise QuantitativeWorkflowError("material cleaning did not create DatasetVersion")
            qc = self.qc.detect(dataset=child, codebook=codebook, questionnaire=self.plan.questionnaire, detection_run_id=f"{run_id}:qc:{child.version_id}")
            updates = dict(state)
            updates["cleaned_dataset_record_id"] = self._persist(child, "dataset", project_id, run_id, dataset_id=child.version_id)
            updates["cleaned_qc_record_id"] = self._persist(qc, "qc", project_id, run_id, dataset_id=child.version_id)
            updates.update(dataset_record_id=updates["cleaned_dataset_record_id"], dataset_version_id=child.version_id, dataset_fingerprint=child.dataset_fingerprint, qc_record_id=updates["cleaned_qc_record_id"], qc_fingerprint=qc.fingerprint, cleaning_status="CLEANED")
            raise QuantitativeApprovalRequired(subject_type="QC", subject_id=updates["qc_record_id"], subject_fingerprint=qc.fingerprint, state_updates=updates)
        approval_id = state.get("cleaned_qc_approval_id")
        if not approval_id: raise QuantitativeApprovalRequired(subject_type="QC", subject_id=state["qc_record_id"], subject_fingerprint=state["qc_fingerprint"])
        self.approvals.require_current(approval_id, project_id=project_id, subject_fingerprint=state["qc_fingerprint"])
        return state

    def _quant_weightset(self, project_id, run_id, state):
        dataset = self._load(state, "dataset_record_id", project_id, DatasetVersion)
        if self.plan.weight_mode == "CONSTRUCT_FROM_TARGET_MARGINS":
            codebook = self._load(state, "codebook_record_id", project_id, CodebookVersion)
            if self.plan.weighting_target_plan is None: raise QuantitativeWorkflowError("target-margin mode requires WeightingTargetPlan")
            weight_set = self.target_weights.construct(dataset=dataset, codebook=codebook, plan=self.plan.weighting_target_plan)
        elif self.plan.weight_mode == "IMPORT_PRECOMPUTED_WEIGHTSET":
            weight_set = self.weights.from_separate_keyed_rows(dataset=dataset, source_bytes_checksum=self.plan.weight_source_checksum, parser_name="fixture-import", parser_version="1", key_specification="technical-id", rows=self.plan.imported_weight_rows)
        else:
            raise QuantitativeWorkflowError("unsupported WeightSet construction mode")
        state["weight_set_record_id"] = self._persist(weight_set, "weightset", project_id, run_id, dataset_id=dataset.version_id)
        state["weight_set_id"], state["weight_set_fingerprint"] = weight_set.weight_set_id, weight_set.reproducibility_fingerprint
        return state

    def _quant_weight_approval(self, project_id, run_id, state):
        approval_id = state.get("weight_approval_id")
        if not approval_id: raise QuantitativeApprovalRequired(subject_type="WEIGHTSET", subject_id=state["weight_set_id"], subject_fingerprint=state["weight_set_fingerprint"])
        durable = self.approvals.require_current(approval_id, project_id=project_id, subject_fingerprint=state["weight_set_fingerprint"])
        weight_set = self._load(state, "weight_set_record_id", project_id, WeightSet)
        accepted = approve_weight_set(weight_set=weight_set, approver_id=durable.actor_id, approved_at=durable.decided_at, digest_provider=self.digest)
        state["analytical_weight_approval_record_id"] = self._persist(accepted, "weight-approval", project_id, run_id, dataset_id=weight_set.dataset_version_id, accepted=True)
        return state

    def _view(self, dataset, qc, weight_set, approval, spec, codebook):
        quality = assess_dataset_quality(dataset=dataset, qc_run=qc, manager_approved=True, approval_fingerprint=approval.fingerprint, digest_provider=self.digest)
        if quality.state is not DatasetQualityState.QC_APPROVED: raise QuantitativeWorkflowError("dataset QC is not approved")
        refs = self.cross_tab.eligible_respondent_refs(dataset=dataset, codebook=codebook, specification=spec) if isinstance(spec, CrossTabAnalysisSpecification) else self.numeric.eligible_respondent_refs(dataset=dataset, codebook=codebook, specification=spec)
        return build_analytical_view(dataset=dataset, quality=quality, specification=spec, mode=WeightingMode.WEIGHTED if spec.weighting_status == "WEIGHTED" else WeightingMode.UNWEIGHTED, respondent_refs=refs, digest_provider=self.digest, weight_set=weight_set if spec.weighting_status == "WEIGHTED" else None, approval=approval if spec.weighting_status == "WEIGHTED" else None)

    def _quant_analysis(self, project_id, run_id, state):
        dataset = self._load(state, "dataset_record_id", project_id, DatasetVersion); codebook = self._load(state, "codebook_record_id", project_id, CodebookVersion); qc = self._load(state, "qc_record_id", project_id, QualityControlRun); weights = self._load(state, "weight_set_record_id", project_id, WeightSet)
        qc_approval_id = state.get("cleaned_qc_approval_id") or state["qc_approval_id"]
        qc_approval = self.approvals.require_current(qc_approval_id, project_id=project_id, subject_fingerprint=qc.fingerprint)
        self.approvals.require_current(state["weight_approval_id"], project_id=project_id, subject_fingerprint=weights.reproducibility_fingerprint)
        weight_approval = self._load(state, "analytical_weight_approval_record_id", project_id, WeightSetApproval)
        results = list(self.one_way.compute(dataset=dataset, codebook=codebook, specification=self.plan.one_way))
        cross_view = self._view(dataset, qc, weights, weight_approval, self.plan.cross_tab, codebook)
        table, cross_results = self.cross_tab.compute(dataset=dataset, codebook=codebook, specification=self.plan.cross_tab, view=cross_view, weight_set=weights); results.extend(cross_results)
        numeric_view = self._view(dataset, qc, weights, weight_approval, self.plan.numeric, codebook); results.extend(self.numeric.compute(dataset=dataset, codebook=codebook, specification=self.plan.numeric, view=numeric_view, weight_set=weights if self.plan.numeric.weighting_status == "WEIGHTED" else None))
        nps_view = self._view(dataset, qc, weights, weight_approval, self.plan.nps, codebook); results.extend(self.kpi.compute_nps(dataset=dataset, codebook=codebook, specification=self.plan.nps, view=nps_view, weight_set=weights if self.plan.nps.weighting_status == "WEIGHTED" else None))
        ids=[]
        for result in results: ids.append(self._persist(result, "stat", project_id, run_id, dataset_id=dataset.version_id))
        table_id = self._persist(table, "table", project_id, run_id, dataset_id=dataset.version_id)
        manifest_fp = canonical_digest({"dataset":dataset.dataset_fingerprint,"results":ids,"tables":[table_id]}, digest_provider=self.digest)
        manifest = QuantitativeAnalysisManifest(f"analysis-{manifest_fp}", dataset.version_id, tuple(ids), (table_id,), (), manifest_fp)
        state["analysis_manifest_record_id"] = self._persist(manifest, "analysis-manifest", project_id, run_id, dataset_id=dataset.version_id)
        return state

    def _results(self, state, project_id):
        manifest = self._load(state, "analysis_manifest_record_id", project_id, QuantitativeAnalysisManifest)
        return tuple(self.state.load(item, project_id=project_id, expected_type=StatisticalResult) for item in manifest.statistical_result_record_ids)

    def _quant_findings(self, project_id, run_id, state):
        generated = self.findings.generate(statistical_results=self._results(state, project_id))
        state["finding_generation_record_id"] = self._persist(generated, "finding-generation", project_id, run_id)
        return state

    def _quant_insights(self, project_id, run_id, state):
        generated = self._load(state, "finding_generation_record_id", project_id, QuantitativeFindingGenerationResult)
        insights = self.insights.generate(findings=generated.accepted_findings)
        state["insight_generation_record_id"] = self._persist(insights, "insight-generation", project_id, run_id)
        return state

    def _quant_report(self, project_id, run_id, state):
        findings = self._load(state, "finding_generation_record_id", project_id, QuantitativeFindingGenerationResult); insights = self._load(state, "insight_generation_record_id", project_id, QuantitativeInsightGenerationResult)
        report = self.reports.compose(findings=findings.accepted_findings, insights=insights.accepted_insights)
        state["report_composition_record_id"] = self._persist(report, "report-composition", project_id, run_id)
        return state

    def _quant_complete(self, project_id, run_id, state):
        required = ("dataset_record_id", "qc_record_id", "weight_set_record_id", "analysis_manifest_record_id", "finding_generation_record_id", "insight_generation_record_id", "report_composition_record_id")
        if any(not state.get(key) for key in required): raise QuantitativeWorkflowError("terminal Quantitative authority is incomplete")
        dataset=self._load(state,"dataset_record_id",project_id,DatasetVersion); qc=self._load(state,"qc_record_id",project_id,QualityControlRun); weights=self._load(state,"weight_set_record_id",project_id,WeightSet)
        manifest=self._load(state,"analysis_manifest_record_id",project_id,QuantitativeAnalysisManifest); findings=self._load(state,"finding_generation_record_id",project_id,QuantitativeFindingGenerationResult); insights=self._load(state,"insight_generation_record_id",project_id,QuantitativeInsightGenerationResult); report=self._load(state,"report_composition_record_id",project_id,QuantitativeReportCompositionResult)
        if report.accepted_report is None: raise QuantitativeWorkflowError("terminal Quantitative report is not accepted")
        result_ids=tuple(self.state.load(record_id,project_id=project_id,expected_type=StatisticalResult).result_id for record_id in manifest.statistical_result_record_ids)
        payload={"run":run_id,"dataset":dataset.dataset_fingerprint,"qc":qc.fingerprint,"weights":weights.reproducibility_fingerprint,"results":result_ids,"findings":findings.generation_fingerprint,"insights":insights.generation_fingerprint,"report":report.composition_fingerprint}
        fp=canonical_digest(payload,digest_provider=self.digest)
        limitation = (
            "Synthetic offline vertical; no live LLM."
            if self.generation_mode == "offline"
            else "Synthetic dataset vertical with production Quantitative generation."
        )
        terminal=QuantitativeTerminalResult(result_id=f"terminal-{fp}",project_id=project_id,run_id=run_id,methodology="QUANTITATIVE",dataset_version_id=dataset.version_id,dataset_fingerprint=dataset.dataset_fingerprint,qc_status="APPROVED",cleaning_lineage=tuple(item for item in (dataset.parent_version_id,dataset.version_id) if item),weight_set_id=weights.weight_set_id,weight_set_fingerprint=weights.reproducibility_fingerprint,weight_approval_id=state["weight_approval_id"],statistical_result_ids=result_ids,accepted_finding_count=len(findings.accepted_findings),rejected_finding_count=len(findings.rejected_findings),accepted_insight_count=len(insights.accepted_insights),rejected_insight_count=len(insights.rejected_insights),report_id=report.accepted_report.report_id,report_status=report.accepted_report.validation_status.value,limitations=(limitation,),execution_status="COMPLETED",terminal_outcome=QuantitativeTerminalOutcome.COMPLETED,fingerprint=fp)
        state["terminal_result_record_id"]=self._persist(terminal,"terminal",project_id,run_id,dataset_id=dataset.version_id,accepted=True)
        state["terminal_authority_status"] = "COMPLETE"
        return state

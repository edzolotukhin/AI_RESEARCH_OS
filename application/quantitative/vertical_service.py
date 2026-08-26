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
from domain.quantitative.analysis_execution import QuantitativeAnalysisExecutionManifest
from domain.quantitative.finding_lineage import DesignAwareFindingInputAuthority, QuantitativeFindingCoverageManifest, QuantitativeFindingDesignLineageManifest
from domain.quantitative.insight_lineage import DesignAwareInsightInputAuthority, QuantitativeInsightCoverageManifest, QuantitativeInsightDesignLineageManifest
from domain.quantitative.report_lineage import DesignAwareReportInputAuthority
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
    one_way: AnalysisSpecification | None
    cross_tab: CrossTabAnalysisSpecification | None
    numeric: NumericAnalysisSpecification | None
    nps: NpsAnalysisSpecification | None
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
        analysis_execution_service=None,
        analysis_execution_projection=None,
        analysis_execution_weights=None,
        finding_lineage_service=None,
        insight_lineage_service=None,
        report_lineage_service=None,
    ) -> None:
        self.plan, self.storage, self.digest = plan, storage, digest_provider
        self.state, self.approvals = state_service, approval_service
        self.findings, self.insights, self.reports = finding_service, insight_service, report_service
        self.generation_mode = generation_mode
        self.analysis_execution_service = analysis_execution_service
        self.analysis_execution_projection = analysis_execution_projection
        self.analysis_execution_weights = dict(analysis_execution_weights or {})
        self.finding_lineage = finding_lineage_service
        self.insight_lineage = insight_lineage_service
        self.report_lineage = report_lineage_service
        self.supports_progress_checkpoint = analysis_execution_service is not None
        self.importer = QuantitativeDatasetImportService(importers=tuple(importers), storage=storage, digest_provider=digest_provider)
        self.qc = DataQualityService(storage=storage, digest_provider=digest_provider)
        self.cleaner = CleaningEngine(storage=storage, digest_provider=digest_provider)
        self.weights = WeightImportService(storage=storage, digest_provider=digest_provider)
        self.target_weights = TargetMarginWeightingService(storage=storage, digest_provider=digest_provider)
        self.one_way = OneWayStatisticsService(storage=storage, digest_provider=digest_provider)
        self.cross_tab = CrossTabStatisticsService(storage=storage, digest_provider=digest_provider)
        self.numeric = NumericStatisticsService(storage=storage, digest_provider=digest_provider)
        self.kpi = KpiStatisticsService(storage=storage, digest_provider=digest_provider)

    def execute_stage(self, stage_id: str, *, project_id: str, run_id: str, safe_state: Mapping[str, str], progress_callback=None) -> Mapping[str, str]:
        handler = getattr(self, f"_{stage_id}", None)
        if handler is None: raise QuantitativeWorkflowError(f"unsupported Quantitative stage: {stage_id}")
        if stage_id == "quant_analysis": return handler(project_id, run_id, dict(safe_state), progress_callback=progress_callback)
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

    def _quant_analysis(self, project_id, run_id, state, progress_callback=None):
        dataset = self._load(state, "dataset_record_id", project_id, DatasetVersion); codebook = self._load(state, "codebook_record_id", project_id, CodebookVersion); qc = self._load(state, "qc_record_id", project_id, QualityControlRun); weights = self._load(state, "weight_set_record_id", project_id, WeightSet)
        qc_approval_id = state.get("cleaned_qc_approval_id") or state["qc_approval_id"]
        qc_approval = self.approvals.require_current(qc_approval_id, project_id=project_id, subject_fingerprint=qc.fingerprint)
        self.approvals.require_current(state["weight_approval_id"], project_id=project_id, subject_fingerprint=weights.reproducibility_fingerprint)
        weight_approval = self._load(state, "analytical_weight_approval_record_id", project_id, WeightSetApproval)
        quality = assess_dataset_quality(dataset=dataset, qc_run=qc, manager_approved=True, approval_fingerprint=qc_approval.fingerprint, digest_provider=self.digest)
        if self.analysis_execution_projection is not None:
            if self.analysis_execution_service is None: raise QuantitativeWorkflowError("design-aware analysis execution service is unavailable")
            manifest=self.analysis_execution_service.execute(project_id=project_id,run_id=run_id,projection=self.analysis_execution_projection,dataset=dataset,codebook=codebook,quality=quality,qc_approval_id=qc_approval_id,qc_approval_fingerprint=qc_approval.fingerprint,weight_authorities=self.analysis_execution_weights,progress_callback=progress_callback)
            result_ids=[]; table_ids=[]; comparison_ids=[]
            for outcome_id in manifest.analysis_outcome_ids:
                outcome=self.analysis_execution_service.repository.get_analysis_outcome(outcome_id,project_id=project_id)
                for artifact in outcome.artifacts:
                    if artifact.artifact_type=="STATISTICAL_RESULT": result_ids.append(artifact.record_id)
                    elif artifact.artifact_type=="STATISTICAL_TABLE": table_ids.append(artifact.record_id)
            for outcome_id in manifest.comparison_outcome_ids:
                outcome=self.analysis_execution_service.repository.get_comparison_outcome(outcome_id,project_id=project_id)
                comparison_ids.extend(x.record_id for x in outcome.artifacts if x.artifact_type=="COMPARISON_RESULT")
            manifest_fp=canonical_digest({"dataset":dataset.dataset_fingerprint,"results":tuple(result_ids),"tables":tuple(table_ids),"comparisons":tuple(comparison_ids),"rd":manifest.fingerprint},digest_provider=self.digest)
            legacy=QuantitativeAnalysisManifest(f"analysis-{manifest_fp}",dataset.version_id,tuple(result_ids),tuple(table_ids),tuple(comparison_ids),manifest_fp)
            state["analysis_manifest_record_id"]=self._persist(legacy,"analysis-manifest",project_id,run_id,dataset_id=dataset.version_id)
            state["analysis_execution_manifest_record_id"]=manifest.manifest_id
            state["analysis_execution_mode"]="DESIGN_AWARE_EXECUTION"
            return state
        if any(value is None for value in (self.plan.one_way,self.plan.cross_tab,self.plan.numeric,self.plan.nps)): raise QuantitativeWorkflowError("dataset-only analysis plan is incomplete")
        results = list(self.one_way.compute(dataset=dataset, codebook=codebook, specification=self.plan.one_way))
        cross_view = self._view(dataset, qc, weights, weight_approval, self.plan.cross_tab, codebook)
        table, cross_results = self.cross_tab.compute(dataset=dataset, codebook=codebook, specification=self.plan.cross_tab, view=cross_view, weight_set=weights); results.extend(cross_results)
        numeric_view = self._view(dataset, qc, weights, weight_approval, self.plan.numeric, codebook); results.extend(self.numeric.compute(dataset=dataset, codebook=codebook, specification=self.plan.numeric, view=numeric_view, weight_set=weights if self.plan.numeric.weighting_status == "WEIGHTED" else None))
        nps_view = self._view(dataset, qc, weights, weight_approval, self.plan.nps, codebook); results.extend(self.kpi.compute_nps(dataset=dataset, codebook=codebook, specification=self.plan.nps, view=nps_view, weight_set=weights if self.plan.nps.weighting_status == "WEIGHTED" else None))
        ids=[self._persist(result,"stat",project_id,run_id,dataset_id=dataset.version_id) for result in results]
        table_id=self._persist(table,"table",project_id,run_id,dataset_id=dataset.version_id)
        manifest_fp=canonical_digest({"dataset":dataset.dataset_fingerprint,"results":ids,"tables":[table_id]},digest_provider=self.digest)
        manifest=QuantitativeAnalysisManifest(f"analysis-{manifest_fp}",dataset.version_id,tuple(ids),(table_id,),(),manifest_fp)
        state["analysis_manifest_record_id"]=self._persist(manifest,"analysis-manifest",project_id,run_id,dataset_id=dataset.version_id)
        state["analysis_execution_mode"]="DATASET_ONLY_EXPLORATORY_EXECUTION"
        if self.analysis_execution_service is not None:
            rd=self.analysis_execution_service.record_dataset_only(project_id=project_id,run_id=run_id,dataset=dataset,codebook=codebook,quality=quality,qc_approval_id=qc_approval_id,qc_approval_fingerprint=qc_approval.fingerprint,legacy_manifest_record_id=state["analysis_manifest_record_id"])
            state["analysis_execution_manifest_record_id"]=rd.manifest_id
        return state
    def _results(self, state, project_id):
        manifest = self._load(state, "analysis_manifest_record_id", project_id, QuantitativeAnalysisManifest)
        return tuple(self.state.load(item, project_id=project_id, expected_type=StatisticalResult) for item in manifest.statistical_result_record_ids)

    def _quant_findings(self, project_id, run_id, state):
        mode = state.get("analysis_execution_mode", "DATASET_ONLY_EXPLORATORY_EXECUTION")
        if mode == "DESIGN_AWARE_EXECUTION":
            if self.finding_lineage is None or self.analysis_execution_projection is None:
                raise QuantitativeWorkflowError("design-aware Finding lineage composition is unavailable")
            manifest_id = state.get("analysis_execution_manifest_record_id")
            if not manifest_id:
                raise QuantitativeWorkflowError("design-aware RD manifest is unavailable")
            manifest = self.analysis_execution_service.repository.get_manifest(manifest_id, project_id=project_id)
            if manifest is None:
                raise QuantitativeWorkflowError("design-aware RD manifest is unavailable")
            dataset = self._load(state, "dataset_record_id", project_id, DatasetVersion)
            codebook = self._load(state, "codebook_record_id", project_id, CodebookVersion)
            candidate = self.finding_lineage.build_input_authority(
                project_id=project_id, run_id=run_id, manifest=manifest,
                projection=self.analysis_execution_projection, dataset=dataset, codebook=codebook,
            )
            existing = self.finding_lineage.repository.get_input_authority(candidate.authority_id, project_id=project_id)
            if existing is not None and existing != candidate:
                raise QuantitativeWorkflowError("conflicting design-aware QI input authority")
            if existing is not None:
                completed = self.finding_lineage.repository.find_manifest_for_input(candidate.authority_id, project_id=project_id, run_id=run_id)
                if completed is not None:
                    generated = self.state.load(completed.finding_generation_record_id, project_id=project_id, expected_type=QuantitativeFindingGenerationResult)
                    if generated.generation_fingerprint != completed.finding_generation_fingerprint:
                        raise QuantitativeWorkflowError("stale completed Finding lineage authority")
                    state["finding_generation_record_id"] = completed.finding_generation_record_id
                    state["finding_input_authority_record_id"] = candidate.authority_id
                    state["finding_lineage_manifest_record_id"] = completed.manifest_id
                    state["finding_coverage_manifest_record_id"] = completed.coverage_manifest_id
                    if not generated.accepted_findings:
                        state["zero_supported_findings"] = "true"
                    return state
                expected_bundle = self.finding_lineage.expected_generation_bundle_fingerprint(candidate)
                recovered = tuple(item for item in self.state.list_for_run(run_id, project_id=project_id, expected_type=QuantitativeFindingGenerationResult) if item.input_result_bundle_fingerprint == expected_bundle)
                if len(recovered) > 1:
                    raise QuantitativeWorkflowError("ambiguous persisted Finding generation authority")
                if recovered:
                    generated = recovered[0]
                    generation_record_id = f"{run_id}:finding-generation:{generated.generation_fingerprint}"
                    lineage, coverage = self.finding_lineage.finalize(authority=candidate, generation_record_id=generation_record_id, generation=generated)
                    state["finding_generation_record_id"] = generation_record_id
                    state["finding_input_authority_record_id"] = candidate.authority_id
                    state["finding_lineage_manifest_record_id"] = lineage.manifest_id
                    state["finding_coverage_manifest_record_id"] = coverage.coverage_id
                    if not generated.accepted_findings:
                        state["zero_supported_findings"] = "true"
                    return state
                raise QuantitativeWorkflowError("indeterminate design-aware QI provider boundary; semantic retry forbidden")
            authority = self.finding_lineage.repository.save_input_authority(candidate)
            results, comparisons = self.finding_lineage.load_results(authority)
            generated = self.findings.generate(
                statistical_results=results,
                comparison_results=comparisons,
                limitations=self.finding_lineage.generation_limitations(authority),
            )
            generation_record_id = self._persist(generated, "finding-generation", project_id, run_id)
            lineage, coverage = self.finding_lineage.finalize(authority=authority, generation_record_id=generation_record_id, generation=generated)
            state["finding_generation_record_id"] = generation_record_id
            state["finding_input_authority_record_id"] = authority.authority_id
            state["finding_lineage_manifest_record_id"] = lineage.manifest_id
            state["finding_coverage_manifest_record_id"] = coverage.coverage_id
        elif mode == "DATASET_ONLY_EXPLORATORY_EXECUTION":
            generated = self.findings.generate(statistical_results=self._results(state, project_id))
            generation_record_id = self._persist(generated, "finding-generation", project_id, run_id)
            state["finding_generation_record_id"] = generation_record_id
            if self.finding_lineage is not None:
                absence = self.finding_lineage.dataset_only_absence(project_id=project_id, run_id=run_id, generation_record_id=generation_record_id, generation=generated)
                state["finding_lineage_absence_record_id"] = absence.absence_id
        else:
            raise QuantitativeWorkflowError("unknown Quantitative analysis execution mode")
        if not generated.accepted_findings:
            state["zero_supported_findings"] = "true"
        return state
    def _quant_insights(self, project_id, run_id, state):
        generated = self._load(state, "finding_generation_record_id", project_id, QuantitativeFindingGenerationResult)
        if not generated.accepted_findings:
            state["zero_supported_findings"] = "true"
            state["insight_generation_status"] = "SKIPPED_NO_SUPPORTED_FINDINGS"
            return state
        mode = state.get("analysis_execution_mode", "DATASET_ONLY_EXPLORATORY_EXECUTION")
        if mode == "DESIGN_AWARE_EXECUTION":
            return self._design_aware_insights(project_id, run_id, state, generated)
        if mode != "DATASET_ONLY_EXPLORATORY_EXECUTION":
            raise QuantitativeWorkflowError("unknown Quantitative analysis execution mode")
        insights = self.insights.generate(findings=generated.accepted_findings)
        generation_record_id = self._persist(insights, "insight-generation", project_id, run_id)
        state["insight_generation_record_id"] = generation_record_id
        if self.insight_lineage is not None:
            absence = self.insight_lineage.dataset_only_absence(project_id=project_id, run_id=run_id, generation_record_id=generation_record_id, generation=insights)
            state["insight_lineage_absence_record_id"] = absence.absence_id
        if not insights.accepted_insights:
            state["zero_supported_insights"] = "true"
        return state

    def _design_aware_insights(self, project_id, run_id, state, generated):
        if self.insight_lineage is None or self.finding_lineage is None or self.analysis_execution_projection is None:
            raise QuantitativeWorkflowError("design-aware RF authority composition is unavailable")
        dataset = self._load(state, "dataset_record_id", project_id, DatasetVersion)
        codebook = self._load(state, "codebook_record_id", project_id, CodebookVersion)
        rd = self._load(state, "analysis_execution_manifest_record_id", project_id, QuantitativeAnalysisExecutionManifest)
        re_input = self._load(state, "finding_input_authority_record_id", project_id, DesignAwareFindingInputAuthority)
        re_manifest = self._load(state, "finding_lineage_manifest_record_id", project_id, QuantitativeFindingDesignLineageManifest)
        re_coverage = self._load(state, "finding_coverage_manifest_record_id", project_id, QuantitativeFindingCoverageManifest)
        current_re = self.finding_lineage.build_input_authority(project_id=project_id, run_id=run_id, manifest=rd, projection=self.analysis_execution_projection, dataset=dataset, codebook=codebook)
        if current_re != re_input:
            raise QuantitativeWorkflowError("stale historical RE authority cannot feed current QJ")
        candidate = self.insight_lineage.build_input_authority(
            project_id=project_id, run_id=run_id,
            generation_record_id=state["finding_generation_record_id"], generation=generated,
            re_input=re_input, re_manifest=re_manifest, re_coverage=re_coverage,
        )
        existing = self.insight_lineage.repository.get_input_authority(candidate.authority_id, project_id=project_id)
        if existing is not None:
            if existing != candidate:
                raise QuantitativeWorkflowError("conflicting RF input authority")
            completed = self.insight_lineage.repository.find_manifest_for_input(candidate.authority_id, project_id=project_id, run_id=run_id)
            if completed is not None:
                insights = self.state.load(completed.insight_generation_record_id, project_id=project_id, expected_type=QuantitativeInsightGenerationResult)
                state["insight_generation_record_id"] = completed.insight_generation_record_id
                state["insight_input_authority_record_id"] = candidate.authority_id
                state["insight_lineage_manifest_record_id"] = completed.manifest_id
                state["insight_coverage_manifest_record_id"] = completed.coverage_manifest_id
                if not insights.accepted_insights: state["zero_supported_insights"] = "true"
                return state
            matching = tuple(item for item in self.state.list_for_run(run_id, project_id=project_id, expected_type=QuantitativeInsightGenerationResult) if item.input_finding_bundle_fingerprint == self.insight_lineage.expected_generation_bundle_fingerprint(candidate))
            if len(matching) > 1:
                raise QuantitativeWorkflowError("ambiguous persisted Insight generation")
            if not matching:
                raise QuantitativeWorkflowError("indeterminate QJ provider boundary; retry prohibited")
            insights = matching[0]
            generation_record_id = f"{run_id}:insight-generation:{authority_fingerprint(insights)}"
            lineage, coverage = self.insight_lineage.finalize(authority=candidate, generation_record_id=generation_record_id, generation=insights)
        else:
            authority = self.insight_lineage.repository.save_input_authority(candidate)
            insights = self.insights.generate(findings=generated.accepted_findings, post_validator=self.insight_lineage.compatibility_validator(authority))
            generation_record_id = self._persist(insights, "insight-generation", project_id, run_id)
            lineage, coverage = self.insight_lineage.finalize(authority=authority, generation_record_id=generation_record_id, generation=insights)
        state["insight_generation_record_id"] = generation_record_id
        state["insight_input_authority_record_id"] = candidate.authority_id
        state["insight_lineage_manifest_record_id"] = lineage.manifest_id
        state["insight_coverage_manifest_record_id"] = coverage.coverage_id
        if not insights.accepted_insights:
            state["zero_supported_insights"] = "true"
        return state
    def _quant_report(self, project_id, run_id, state):
        if state.get("zero_supported_findings") == "true":
            state["report_composition_status"] = "SKIPPED_NO_SUPPORTED_FINDINGS"
            return state
        if state.get("zero_supported_insights") == "true":
            state["report_composition_status"] = "SKIPPED_NO_SUPPORTED_INSIGHTS"
            return state
        findings = self._load(state, "finding_generation_record_id", project_id, QuantitativeFindingGenerationResult)
        insights = self._load(state, "insight_generation_record_id", project_id, QuantitativeInsightGenerationResult)
        mode = state.get("analysis_execution_mode", "DATASET_ONLY_EXPLORATORY_EXECUTION")
        if mode == "DESIGN_AWARE_EXECUTION":
            return self._design_aware_report(project_id, run_id, state, findings, insights)
        if mode != "DATASET_ONLY_EXPLORATORY_EXECUTION":
            raise QuantitativeWorkflowError("unknown Quantitative analysis execution mode")
        report = self.reports.compose(findings=findings.accepted_findings, insights=insights.accepted_insights)
        record_id = self._persist(report, "report-composition", project_id, run_id)
        state["report_composition_record_id"] = record_id
        if self.report_lineage is not None:
            absence = self.report_lineage.dataset_only_absence(
                project_id=project_id, run_id=run_id,
                report_composition_record_id=record_id, composition=report,
            )
            state["report_lineage_absence_record_id"] = absence.absence_id
        return state

    def _design_aware_report(self, project_id, run_id, state, findings, insights):
        if self.report_lineage is None or self.insight_lineage is None or self.finding_lineage is None or self.analysis_execution_projection is None:
            raise QuantitativeWorkflowError("design-aware RG authority composition is unavailable")
        dataset = self._load(state, "dataset_record_id", project_id, DatasetVersion)
        codebook = self._load(state, "codebook_record_id", project_id, CodebookVersion)
        rd = self._load(state, "analysis_execution_manifest_record_id", project_id, QuantitativeAnalysisExecutionManifest)
        re_input = self._load(state, "finding_input_authority_record_id", project_id, DesignAwareFindingInputAuthority)
        re_manifest = self._load(state, "finding_lineage_manifest_record_id", project_id, QuantitativeFindingDesignLineageManifest)
        re_coverage = self._load(state, "finding_coverage_manifest_record_id", project_id, QuantitativeFindingCoverageManifest)
        rf_input = self._load(state, "insight_input_authority_record_id", project_id, DesignAwareInsightInputAuthority)
        rf_manifest = self._load(state, "insight_lineage_manifest_record_id", project_id, QuantitativeInsightDesignLineageManifest)
        rf_coverage = self._load(state, "insight_coverage_manifest_record_id", project_id, QuantitativeInsightCoverageManifest)
        current_re = self.finding_lineage.build_input_authority(
            project_id=project_id, run_id=run_id, manifest=rd,
            projection=self.analysis_execution_projection, dataset=dataset, codebook=codebook,
        )
        if current_re != re_input:
            raise QuantitativeWorkflowError("stale historical RE authority cannot feed current QK")
        current_rf = self.insight_lineage.build_input_authority(
            project_id=project_id, run_id=run_id,
            generation_record_id=state["finding_generation_record_id"], generation=findings,
            re_input=re_input, re_manifest=re_manifest, re_coverage=re_coverage,
        )
        if current_rf != rf_input:
            raise QuantitativeWorkflowError("stale historical RF authority cannot feed current QK")
        candidate = self.report_lineage.build_input_authority(
            project_id=project_id, run_id=run_id,
            finding_generation_record_id=state["finding_generation_record_id"], findings=findings,
            insight_generation_record_id=state["insight_generation_record_id"], insights=insights,
            re_input=re_input, re_manifest=re_manifest, re_coverage=re_coverage,
            rf_input=rf_input, rf_manifest=rf_manifest, rf_coverage=rf_coverage,
        )
        existing = self.report_lineage.repository.get_input_authority(candidate.authority_id, project_id=project_id)
        if existing is not None:
            if existing != candidate:
                raise QuantitativeWorkflowError("conflicting RG input authority")
            manifest = self.report_lineage.repository.find_manifest_for_input(candidate.authority_id, project_id=project_id, run_id=run_id)
            coverage = self.report_lineage.repository.find_coverage_for_input(candidate.authority_id, project_id=project_id, run_id=run_id)
            if manifest is not None:
                report = self.state.load(manifest.report_composition_record_id, project_id=project_id, expected_type=QuantitativeReportCompositionResult)
                if report.composition_fingerprint != manifest.report_composition_fingerprint or coverage is None or coverage.coverage_id != manifest.coverage_manifest_id:
                    raise QuantitativeWorkflowError("stale completed RG authority")
                state["report_composition_record_id"] = manifest.report_composition_record_id
                state["report_input_authority_record_id"] = candidate.authority_id
                state["report_lineage_manifest_record_id"] = manifest.manifest_id
                state["report_coverage_manifest_record_id"] = coverage.coverage_id
                return state
            if coverage is not None:
                report = self.state.load(coverage.report_composition_record_id, project_id=project_id, expected_type=QuantitativeReportCompositionResult)
                if report.composition_fingerprint != coverage.report_composition_fingerprint or report.accepted_report is not None:
                    raise QuantitativeWorkflowError("conflicting rejected RG authority")
                state["report_composition_record_id"] = coverage.report_composition_record_id
                state["report_input_authority_record_id"] = candidate.authority_id
                state["report_coverage_manifest_record_id"] = coverage.coverage_id
                return state
            matches = tuple(item for item in self.state.list_for_run(run_id, project_id=project_id, expected_type=QuantitativeReportCompositionResult) if item.input_support_bundle_fingerprint == self.report_lineage.expected_report_bundle_fingerprint(candidate))
            if len(matches) > 1:
                raise QuantitativeWorkflowError("ambiguous persisted Report composition")
            if not matches:
                raise QuantitativeWorkflowError("indeterminate QK provider boundary; retry prohibited")
            report = matches[0]
            record_id = f"{run_id}:report-composition:{report.composition_fingerprint}"
            manifest, coverage = self.report_lineage.finalize(authority=candidate, report_composition_record_id=record_id, composition=report)
        else:
            authority = self.report_lineage.repository.save_input_authority(candidate)
            report = self.reports.compose_design_aware(
                findings=findings.accepted_findings,
                insights=insights.accepted_insights,
                bundle=self.report_lineage.report_bundle(authority),
                post_validator=self.report_lineage.compatibility_validator(authority),
            )
            record_id = self._persist(report, "report-composition", project_id, run_id)
            manifest, coverage = self.report_lineage.finalize(authority=authority, report_composition_record_id=record_id, composition=report)
        state["report_composition_record_id"] = record_id
        state["report_input_authority_record_id"] = candidate.authority_id
        state["report_coverage_manifest_record_id"] = coverage.coverage_id
        if manifest is not None:
            state["report_lineage_manifest_record_id"] = manifest.manifest_id
        return state
    def _quant_complete(self, project_id, run_id, state):
        if state.get("zero_supported_findings") == "true":
            return self._complete_without_supported_findings(project_id, run_id, state)
        if state.get("zero_supported_insights") == "true":
            return self._complete_without_supported_insights(project_id, run_id, state)
        required = ("dataset_record_id", "qc_record_id", "weight_set_record_id", "analysis_manifest_record_id", "finding_generation_record_id", "insight_generation_record_id", "report_composition_record_id")
        if any(not state.get(key) for key in required): raise QuantitativeWorkflowError("terminal Quantitative authority is incomplete")
        dataset=self._load(state,"dataset_record_id",project_id,DatasetVersion); qc=self._load(state,"qc_record_id",project_id,QualityControlRun); weights=self._load(state,"weight_set_record_id",project_id,WeightSet)
        manifest=self._load(state,"analysis_manifest_record_id",project_id,QuantitativeAnalysisManifest); findings=self._load(state,"finding_generation_record_id",project_id,QuantitativeFindingGenerationResult); insights=self._load(state,"insight_generation_record_id",project_id,QuantitativeInsightGenerationResult); report=self._load(state,"report_composition_record_id",project_id,QuantitativeReportCompositionResult)
        if report.accepted_report is None:
            return self._complete_without_supported_report(project_id, run_id, state, dataset, qc, weights, manifest, findings, insights, report)
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

    def _complete_without_supported_insights(self, project_id, run_id, state):
        required = (
            "dataset_record_id", "qc_record_id", "weight_set_record_id",
            "analysis_manifest_record_id", "finding_generation_record_id",
            "insight_generation_record_id",
        )
        if any(not state.get(key) for key in required):
            raise QuantitativeWorkflowError("zero-Insight terminal authority is incomplete")
        dataset=self._load(state,"dataset_record_id",project_id,DatasetVersion); qc=self._load(state,"qc_record_id",project_id,QualityControlRun); weights=self._load(state,"weight_set_record_id",project_id,WeightSet)
        manifest=self._load(state,"analysis_manifest_record_id",project_id,QuantitativeAnalysisManifest); findings=self._load(state,"finding_generation_record_id",project_id,QuantitativeFindingGenerationResult); insights=self._load(state,"insight_generation_record_id",project_id,QuantitativeInsightGenerationResult)
        if not findings.accepted_findings or insights.accepted_insights:
            raise QuantitativeWorkflowError("zero-Insight terminal conflicts with accepted authority")
        return self._persist_controlled_terminal(
            project_id, run_id, state, dataset, qc, weights, manifest, findings,
            insights, None,
            QuantitativeTerminalOutcome.COMPLETED_WITH_NO_SUPPORTED_INSIGHTS,
            "NOT_GENERATED_NO_SUPPORTED_INSIGHTS",
            "Finding authority was accepted, but deterministic QJ validation accepted no supported Insights; Report generation was skipped.",
        )

    def _complete_without_supported_report(self, project_id, run_id, state, dataset, qc, weights, manifest, findings, insights, report):
        if not findings.accepted_findings or not insights.accepted_insights or report.accepted_report is not None:
            raise QuantitativeWorkflowError("rejected-Report terminal conflicts with accepted authority")
        return self._persist_controlled_terminal(
            project_id, run_id, state, dataset, qc, weights, manifest, findings,
            insights, report,
            QuantitativeTerminalOutcome.COMPLETED_WITH_NO_SUPPORTED_REPORT,
            "REJECTED_NO_SUPPORTED_REPORT",
            "Findings and Insights were accepted, but deterministic QK validation accepted no supported Report.",
        )

    def _persist_controlled_terminal(self, project_id, run_id, state, dataset, qc, weights, manifest, findings, insights, report, outcome, report_status, limitation):
        result_ids=tuple(self.state.load(record_id,project_id=project_id,expected_type=StatisticalResult).result_id for record_id in manifest.statistical_result_record_ids)
        payload={"run":run_id,"dataset":dataset.dataset_fingerprint,"qc":qc.fingerprint,"weights":weights.reproducibility_fingerprint,"results":result_ids,"findings":findings.generation_fingerprint,"insights":insights.generation_fingerprint,"report":report.composition_fingerprint if report else None,"outcome":outcome.value}
        fp=canonical_digest(payload,digest_provider=self.digest)
        terminal=QuantitativeTerminalResult(result_id=f"terminal-{fp}",project_id=project_id,run_id=run_id,methodology="QUANTITATIVE",dataset_version_id=dataset.version_id,dataset_fingerprint=dataset.dataset_fingerprint,qc_status="APPROVED",cleaning_lineage=tuple(item for item in (dataset.parent_version_id,dataset.version_id) if item),weight_set_id=weights.weight_set_id,weight_set_fingerprint=weights.reproducibility_fingerprint,weight_approval_id=state["weight_approval_id"],statistical_result_ids=result_ids,accepted_finding_count=len(findings.accepted_findings),rejected_finding_count=len(findings.rejected_findings),accepted_insight_count=len(insights.accepted_insights),rejected_insight_count=len(insights.rejected_insights),report_id="",report_status=report_status,limitations=(limitation,),execution_status="COMPLETED",terminal_outcome=outcome,fingerprint=fp)
        state["terminal_result_record_id"]=self._persist(terminal,"terminal",project_id,run_id,dataset_id=dataset.version_id,accepted=True)
        state["terminal_authority_status"] = outcome.value.replace("COMPLETED", "COMPLETE", 1)
        return state
    def _complete_without_supported_findings(self, project_id, run_id, state):
        required = (
            "dataset_record_id", "qc_record_id", "weight_set_record_id",
            "analysis_manifest_record_id", "finding_generation_record_id",
        )
        if any(not state.get(key) for key in required):
            raise QuantitativeWorkflowError("zero-Finding terminal authority is incomplete")
        dataset = self._load(state, "dataset_record_id", project_id, DatasetVersion)
        qc = self._load(state, "qc_record_id", project_id, QualityControlRun)
        weights = self._load(state, "weight_set_record_id", project_id, WeightSet)
        manifest = self._load(
            state, "analysis_manifest_record_id", project_id, QuantitativeAnalysisManifest
        )
        findings = self._load(
            state, "finding_generation_record_id", project_id,
            QuantitativeFindingGenerationResult,
        )
        if findings.accepted_findings:
            raise QuantitativeWorkflowError("zero-Finding terminal conflicts with accepted authority")
        result_ids = tuple(
            self.state.load(
                record_id, project_id=project_id, expected_type=StatisticalResult
            ).result_id
            for record_id in manifest.statistical_result_record_ids
        )
        outcome = QuantitativeTerminalOutcome.COMPLETED_WITH_NO_SUPPORTED_FINDINGS
        payload = {
            "run": run_id,
            "dataset": dataset.dataset_fingerprint,
            "qc": qc.fingerprint,
            "weights": weights.reproducibility_fingerprint,
            "results": result_ids,
            "findings": findings.generation_fingerprint,
            "outcome": outcome.value,
        }
        fp = canonical_digest(payload, digest_provider=self.digest)
        terminal = QuantitativeTerminalResult(
            result_id=f"terminal-{fp}", project_id=project_id, run_id=run_id,
            methodology="QUANTITATIVE", dataset_version_id=dataset.version_id,
            dataset_fingerprint=dataset.dataset_fingerprint, qc_status="APPROVED",
            cleaning_lineage=tuple(
                item for item in (dataset.parent_version_id, dataset.version_id) if item
            ),
            weight_set_id=weights.weight_set_id,
            weight_set_fingerprint=weights.reproducibility_fingerprint,
            weight_approval_id=state["weight_approval_id"],
            statistical_result_ids=result_ids,
            accepted_finding_count=0,
            rejected_finding_count=len(findings.rejected_findings),
            accepted_insight_count=0, rejected_insight_count=0,
            report_id="", report_status="NOT_GENERATED_NO_SUPPORTED_FINDINGS",
            limitations=(
                "Finding generation completed, but deterministic QH validation "
                "accepted no supported Findings; Insight and Report generation were skipped.",
            ),
            execution_status="COMPLETED", terminal_outcome=outcome,
            fingerprint=fp,
        )
        state["terminal_result_record_id"] = self._persist(
            terminal, "terminal", project_id, run_id,
            dataset_id=dataset.version_id, accepted=True,
        )
        state["terminal_authority_status"] = "COMPLETE_WITH_NO_SUPPORTED_FINDINGS"
        return state

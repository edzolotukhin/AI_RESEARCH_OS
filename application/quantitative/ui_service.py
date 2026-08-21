from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping
from uuid import uuid4

from application.quantitative.dataset_import_service import QuantitativeDatasetImportService
from application.quantitative.state_persistence import QuantitativeStateService
from application.quantitative.quality_control import (
    CleaningEngine, DataQualityService, build_cleaning_decision,
    build_cleaning_decision_set, build_questionnaire_snapshot,
)
from application.quantitative.target_margin_weighting import TargetMarginWeightingService, build_weighting_target_plan
from application.quantitative.workflow import QuantitativeApprovalService
from application.quantitative.workflow import (
    QUANTITATIVE_SAFE_STATE_KEY, QUANTITATIVE_STAGE_SERVICE_KEY,
    QuantitativeStageExecutor, build_quantitative_workflow_template,
)
from domain.quantitative.dataset import CodebookVersion, DatasetFormat, DatasetVersion
from domain.quantitative.quality import ApprovalState, CleaningAction, QualityControlRun, QuestionnaireSnapshot
from domain.quantitative.weighting import WeightSet, WeightingTargetMargin, WeightingTargetPlan, WeightTrimmingPolicy
from domain.quantitative.workflow import QuantitativeApprovalDecision, QuantitativeStudyProjection, QuantitativeTerminalResult, QuantitativeAnalysisManifest


class QuantitativeUiError(ValueError):
    """Safe, user-facing Quantitative operation failure."""


class _QuantitativeWorkflowExecutionFailure(RuntimeError):
    def __init__(self, context) -> None:
        super().__init__("Quantitative workflow execution failed")
        self.context = context


class QuantitativeUiService:
    """Methodology-specific command/query boundary for the minimal QO UI.

    The service never returns protected rows. It only projects aggregate
    metadata and invokes the accepted Quantitative application services.
    """

    MAX_UPLOAD_BYTES = 20 * 1024 * 1024

    def __init__(self, *, project_service, workflow_service, state_service: QuantitativeStateService,
                 digest_provider, storage_factory, importers: tuple[Any, ...],
                 finding_generator, insight_generator, report_generator,
                 generation_mode: str, stage_service_factory=None,
                 durable_workflow_service=None) -> None:
        if generation_mode not in {"offline", "production"}:
            raise ValueError("Quantitative generation mode is not configured")
        if any(item is None for item in (finding_generator, insight_generator, report_generator)):
            raise ValueError("Quantitative generators are not configured")
        if stage_service_factory is None:
            raise ValueError("Quantitative stage service factory is not configured")
        self.projects = project_service
        self.workflows = workflow_service
        self.state = state_service
        self.digest = digest_provider
        self.storage_factory = storage_factory
        self.importers = importers
        self.finding_generator = finding_generator
        self.insight_generator = insight_generator
        self.report_generator = report_generator
        self.generation_mode = generation_mode
        self.stage_service_factory = stage_service_factory
        self.durable_workflow_service = durable_workflow_service
        self._studies: dict[str, QuantitativeStudyProjection] = {}
        self._submission_ids: dict[tuple[str, str], str] = {}

    def create_study(self, *, owner_id: str, title: str, description: str, submission_key: str) -> QuantitativeStudyProjection:
        title, submission_key = title.strip(), submission_key.strip()
        if not title or not submission_key:
            raise QuantitativeUiError("title and submission_key are required")
        existing = self._submission_ids.get((owner_id, submission_key))
        if existing:
            study = self._studies[existing]
            if (study.title, study.description) != (title, description.strip()):
                raise QuantitativeUiError("submission key was already used for different content")
            return study
        study_id = project_id = run_id = str(uuid4())
        self.projects.create_project(title, owner_principal_id=owner_id, project_id=project_id)
        template = build_quantitative_workflow_template()
        self.workflows.publish_template_snapshot(template, project_id=project_id)
        self.workflows.create_workflow_run(
            template,
            project_id=project_id,
            run_id=run_id,
            initially_paused=True,
        )
        study = QuantitativeStudyProjection(study_id, project_id, run_id, title, description.strip(), "WAITING_FOR_DATASET")
        self._studies[study_id] = study
        self._submission_ids[(owner_id, submission_key)] = study_id
        return self._persist_study(study)

    def get(self, study_id: str, *, owner_id: str) -> QuantitativeStudyProjection:
        study = self._studies.get(study_id)
        try:
            project = self.projects.get_project(study_id)
        except Exception as exc:
            raise QuantitativeUiError("Quantitative study not found") from exc
        if project.owner_principal_id != owner_id:
            raise QuantitativeUiError("Quantitative study not found")
        if study is None:
            snapshots = self.state.list_for_run(study_id, project_id=study_id, expected_type=QuantitativeStudyProjection)
            if not snapshots:
                raise QuantitativeUiError("Quantitative study not found")
            study = max(snapshots, key=lambda item: item.revision)
            self._studies[study_id] = study
        run = self.workflows.get_workflow_run(study.run_id)
        if run.status.value == "completed" and not study.terminal_result_record_id:
            try:
                terminal_record_id = self._terminal_record_id(study)
            except (ValueError, StopIteration):
                raise QuantitativeUiError(
                    "Completed Quantitative workflow has no terminal authority"
                ) from None
            study = replace(
                study,
                state="COMPLETED",
                terminal_result_record_id=terminal_record_id,
            )
            self._studies[study_id] = study
        return study

    def upload(self, study_id: str, *, owner_id: str, filename: str, content: bytes,
               overrides: Mapping[str, Any] | None = None) -> QuantitativeStudyProjection:
        study = self.get(study_id, owner_id=owner_id)
        self._require_setup_paused(study)
        suffix = Path(filename).suffix.casefold()
        formats = {".sav": DatasetFormat.SAV, ".xlsx": DatasetFormat.XLSX}
        if suffix not in formats:
            raise QuantitativeUiError("Only SAV and XLSX datasets are supported")
        if not content or len(content) > self.MAX_UPLOAD_BYTES:
            raise QuantitativeUiError("Dataset is empty or exceeds the upload limit")
        if study.dataset_record_id:
            return study
        storage = self.storage_factory(study.project_id, study.run_id)
        try:
            imported = QuantitativeDatasetImportService(
                importers=self.importers, storage=storage, digest_provider=self.digest,
            ).import_bytes(content, filename=Path(filename).name, dataset_format=formats[suffix],
                           dataset_id=f"dataset-{study.study_id}", project_id=study.project_id,
                           run_id=study.run_id, overrides=dict(overrides or {}))
        except Exception as exc:
            raise QuantitativeUiError("Dataset could not be imported safely") from exc
        dataset_id = f"{study.run_id}:dataset:{imported.dataset_version.dataset_fingerprint}"
        codebook_id = f"{study.run_id}:codebook:{imported.codebook.fingerprint}"
        self.state.persist(imported.dataset_version, record_id=dataset_id, project_id=study.project_id,
                           run_id=study.run_id, dataset_version_id=imported.dataset_version.version_id)
        self.state.persist(imported.codebook, record_id=codebook_id, project_id=study.project_id,
                           run_id=study.run_id, dataset_version_id=imported.dataset_version.version_id)
        return self._save(replace(study, state="IMPORTED", dataset_record_id=dataset_id,
                                  codebook_record_id=codebook_id))

    def import_review(self, study_id: str, *, owner_id: str) -> dict[str, Any]:
        study = self.get(study_id, owner_id=owner_id)
        dataset, codebook = self._dataset(study)
        return {
            "study_id": study.study_id, "state": study.state,
            "dataset_version_id": dataset.version_id, "format": dataset.format.value,
            "row_count": dataset.row_count, "variable_count": dataset.variable_count,
            "pii_classification": dataset.pii_classification_status.value,
            "variables": tuple({"name": item.name, "label": item.label,
                                "analytical_type": item.variable_type.value,
                                "missing_status": ("DECLARED" if item.missing_rules else "NONE"),
                                "pii": item.pii_classification.value} for item in codebook.variables),
        }

    def execution_status(self, study_id: str, *, owner_id: str) -> str:
        study = self.get(study_id, owner_id=owner_id)
        return self.workflows.get_workflow_run(study.run_id).status.value

    def run_qc(self, study_id: str, *, owner_id: str, questionnaire: QuestionnaireSnapshot) -> QuantitativeStudyProjection:
        study = self.get(study_id, owner_id=owner_id)
        self._require_setup_paused(study)
        dataset, codebook = self._dataset(study)
        storage = self.storage_factory(study.project_id, study.run_id)
        try:
            qc = DataQualityService(storage=storage, digest_provider=self.digest).detect(
                dataset=dataset, codebook=codebook, questionnaire=questionnaire,
                detection_run_id=f"{study.run_id}:qc:{dataset.version_id}")
        except Exception as exc:
            raise QuantitativeUiError("Quality control could not be completed") from exc
        record_id = f"{study.run_id}:qc:{qc.fingerprint}"
        self.state.persist(qc, record_id=record_id, project_id=study.project_id, run_id=study.run_id,
                           dataset_version_id=dataset.version_id)
        return self._save(replace(study, state="AWAITING_QC_APPROVAL", qc_record_id=record_id,
                                  qc_approval_id=None))

    def run_default_qc(self, study_id: str, *, owner_id: str) -> QuantitativeStudyProjection:
        study = self.get(study_id, owner_id=owner_id)
        _, codebook = self._dataset(study)
        questionnaire = build_questionnaire_snapshot(
            snapshot_id=f"questionnaire-{study.study_id}", version="QO-1",
            codebook_version_id=codebook.codebook_version_id,
            question_variable_bindings=tuple((item.name, item.variable_id) for item in codebook.variables),
            digest_provider=self.digest,
        )
        return self.run_qc(study_id, owner_id=owner_id, questionnaire=questionnaire)

    def approve_qc(self, study_id: str, *, owner_id: str, actor_id: str, fingerprint: str,
                   decision: str, rationale: str) -> QuantitativeStudyProjection:
        study = self.get(study_id, owner_id=owner_id)
        self._require_setup_paused(study)
        qc = self.state.load(study.qc_record_id or "", project_id=study.project_id, expected_type=QualityControlRun)
        if qc.fingerprint != fingerprint:
            raise QuantitativeUiError("QC approval is stale")
        approval = QuantitativeApprovalService(self.state, self.digest).record(
            approval_id=str(uuid4()), project_id=study.project_id, run_id=study.run_id,
            subject_type="QC", subject_id=study.qc_record_id or "", subject_fingerprint=fingerprint,
            decision=QuantitativeApprovalDecision(decision), actor_id=actor_id,
            decided_at=datetime.now(timezone.utc).isoformat(), rationale=rationale)
        next_state = "WEIGHTING_REQUIRED" if decision == "APPROVED" else "FAILED"
        return self._save(replace(study, state=next_state, qc_approval_id=approval.approval_id))

    def apply_recode_cleaning(self, study_id: str, *, owner_id: str, actor_id: str,
                              variable_name: str, replacements: Mapping[str, Any]) -> QuantitativeStudyProjection:
        study = self.get(study_id, owner_id=owner_id)
        self._require_setup_paused(study)
        if study.state != "AWAITING_QC_APPROVAL":
            raise QuantitativeUiError("Cleaning requires current QC review")
        dataset, codebook = self._dataset(study)
        variable = next((item for item in codebook.variables if item.name == variable_name), None)
        if variable is None or not variable.analytically_eligible:
            raise QuantitativeUiError("Cleaning variable is unavailable or restricted")
        storage = self.storage_factory(study.project_id, study.run_id)
        rows, refs = storage.get_parsed_rows(dataset.version_id), storage.get_respondent_lineage(dataset.version_id)
        position = next(index for index, item in enumerate(codebook.variables) if item.variable_id == variable.variable_id)
        decisions = []
        for row, ref in zip(rows, refs):
            old = row[position]
            if str(old) not in replacements:
                continue
            decisions.append(build_cleaning_decision(
                parent=dataset, action=CleaningAction.RECODE, affected_refs=(ref,),
                variable_ids=(variable.variable_id,), transformation=(("from", old), ("to", replacements[str(old)])),
                rationale="Authorized deterministic UI recode", actor_id=actor_id, issue_ids=(),
                digest_provider=self.digest))
        if not decisions:
            raise QuantitativeUiError("Cleaning mapping does not match any respondent values")
        decision_set = build_cleaning_decision_set(
            parent=dataset, decisions=tuple(decisions), approval_state=ApprovalState.APPROVED,
            approver_id=actor_id, approved_at=datetime.now(timezone.utc).isoformat(), digest_provider=self.digest)
        try:
            cleaned = CleaningEngine(storage=storage, digest_provider=self.digest).execute(
                parent=dataset, codebook=codebook, decision_set=decision_set)
        except Exception as exc:
            raise QuantitativeUiError("Approved cleaning could not be applied safely") from exc
        if cleaned is None:
            raise QuantitativeUiError("Cleaning produced no material DatasetVersion")
        questionnaire = build_questionnaire_snapshot(
            snapshot_id=f"questionnaire-{study.study_id}-cleaned", version="QO-1",
            codebook_version_id=codebook.codebook_version_id,
            question_variable_bindings=tuple((item.name, item.variable_id) for item in codebook.variables),
            answer_domains=((variable.variable_id, tuple(replacements.values())),), digest_provider=self.digest)
        qc = DataQualityService(storage=storage, digest_provider=self.digest).detect(
            dataset=cleaned, codebook=codebook, questionnaire=questionnaire,
            detection_run_id=f"{study.run_id}:qc:{cleaned.version_id}")
        dataset_id=f"{study.run_id}:dataset:{cleaned.dataset_fingerprint}"
        qc_id=f"{study.run_id}:qc:{qc.fingerprint}"
        self.state.persist(cleaned, record_id=dataset_id, project_id=study.project_id, run_id=study.run_id,
                           dataset_version_id=cleaned.version_id)
        self.state.persist(qc, record_id=qc_id, project_id=study.project_id, run_id=study.run_id,
                           dataset_version_id=cleaned.version_id)
        return self._save(replace(study, state="AWAITING_QC_APPROVAL", dataset_record_id=dataset_id,
                                  qc_record_id=qc_id, qc_approval_id=None, target_plan_record_id=None,
                                  weight_set_record_id=None, weight_approval_id=None))

    def construct_weights(self, study_id: str, *, owner_id: str, plan: WeightingTargetPlan) -> QuantitativeStudyProjection:
        study = self.get(study_id, owner_id=owner_id)
        self._require_setup_paused(study)
        if study.state != "WEIGHTING_REQUIRED" or not study.qc_approval_id:
            raise QuantitativeUiError("Current QC approval is required before weighting")
        dataset, codebook = self._dataset(study)
        storage = self.storage_factory(study.project_id, study.run_id)
        try:
            weights = TargetMarginWeightingService(storage=storage, digest_provider=self.digest).construct(
                dataset=dataset, codebook=codebook, plan=plan)
        except Exception as exc:
            raise QuantitativeUiError("Target-margin weighting failed validation or convergence") from exc
        plan_id = f"{study.run_id}:weight-plan:{plan.fingerprint}"
        weight_id = f"{study.run_id}:weightset:{weights.reproducibility_fingerprint}"
        self.state.persist(plan, record_id=plan_id, project_id=study.project_id, run_id=study.run_id,
                           dataset_version_id=dataset.version_id)
        self.state.persist(weights, record_id=weight_id, project_id=study.project_id, run_id=study.run_id,
                           dataset_version_id=dataset.version_id)
        return self._save(replace(study, state="AWAITING_WEIGHT_APPROVAL",
                                  target_plan_record_id=plan_id, weight_set_record_id=weight_id,
                                  weight_approval_id=None))

    def construct_weights_from_payload(self, study_id: str, *, owner_id: str,
                                       targets: Mapping[str, Mapping[str, Any]]) -> QuantitativeStudyProjection:
        study = self.get(study_id, owner_id=owner_id)
        dataset, codebook = self._dataset(study)
        by_name = {item.name: item for item in codebook.variables}
        margins = []
        for variable_name, categories in targets.items():
            variable = by_name.get(variable_name)
            if variable is None or not isinstance(categories, Mapping):
                raise QuantitativeUiError("Target category mapping is invalid")
            values = []
            labels = {str(label): code for code, label in variable.value_labels}
            known_codes = {str(code): code for code, _ in variable.value_labels}
            for supplied, raw_target in categories.items():
                code = known_codes.get(str(supplied), labels.get(str(supplied), supplied))
                values.append((code, Decimal(str(raw_target)) / Decimal(100)))
            margins.append(WeightingTargetMargin(variable.variable_id, tuple(values)))
        plan = build_weighting_target_plan(
            plan_id=f"target-plan-{study.study_id}-{study.revision}", dataset=dataset,
            margins=tuple(margins), target_source="authorized UI entry",
            target_total_tolerance=Decimal("0.000001"), convergence_tolerance=Decimal("0.000001"),
            maximum_iterations=100, minimum_weight=Decimal("0.05"), maximum_weight=Decimal("20"),
            trimming_policy=WeightTrimmingPolicy.NONE, digest_provider=self.digest,
        )
        return self.construct_weights(study_id, owner_id=owner_id, plan=plan)

    def approve_weights(self, study_id: str, *, owner_id: str, actor_id: str,
                        fingerprint: str, decision: str, rationale: str) -> QuantitativeStudyProjection:
        study = self.get(study_id, owner_id=owner_id)
        self._require_setup_paused(study)
        weights = self.state.load(study.weight_set_record_id or "", project_id=study.project_id, expected_type=WeightSet)
        if weights.reproducibility_fingerprint != fingerprint:
            raise QuantitativeUiError("WeightSet approval is stale")
        approval = QuantitativeApprovalService(self.state, self.digest).record(
            approval_id=str(uuid4()), project_id=study.project_id, run_id=study.run_id,
            subject_type="WEIGHTSET", subject_id=weights.weight_set_id,
            subject_fingerprint=fingerprint, decision=QuantitativeApprovalDecision(decision),
            actor_id=actor_id, decided_at=datetime.now(timezone.utc).isoformat(), rationale=rationale)
        next_state = "READY_TO_ANALYZE" if decision == "APPROVED" else "FAILED"
        return self._save(replace(study, state=next_state, weight_approval_id=approval.approval_id))

    def weighting_diagnostics(self, study_id: str, *, owner_id: str) -> dict[str, Any]:
        study = self.get(study_id, owner_id=owner_id)
        weights = self.state.load(study.weight_set_record_id or "", project_id=study.project_id, expected_type=WeightSet)
        plan = self.state.load(study.target_plan_record_id or "", project_id=study.project_id, expected_type=WeightingTargetPlan)
        diagnostic = weights.convergence_diagnostic
        targets={(margin.variable_id,str(category)):target for margin in plan.margins for category,target in margin.category_targets}
        margins=tuple({"variable_id":variable_id,"category":category,"target":str(targets.get((variable_id,str(category)),"")),
                       "achieved":str(achieved),"error":str(abs(achieved-targets[(variable_id,str(category))])) if (variable_id,str(category)) in targets else None}
                      for variable_id,values in (diagnostic.achieved_margins if diagnostic else ()) for category,achieved in values)
        return {"state": study.state, "weight_set_id": weights.weight_set_id,
                "converged": diagnostic.converged if diagnostic else None,
                "iterations": diagnostic.iterations_used if diagnostic else None,
                "maximum_margin_error": str(diagnostic.maximum_absolute_margin_error) if diagnostic else None,
                "minimum_weight": str(weights.minimum_weight),
                "maximum_weight": str(weights.maximum_weight),
                "mean_weight": str(weights.mean_weight),
                "effective_sample_size": str(weights.effective_sample_size) if weights.effective_sample_size is not None else None,
                "margins": margins}

    def resume_workflow(self, study_id: str, *, owner_id: str) -> QuantitativeStudyProjection:
        study = self.get(study_id, owner_id=owner_id)
        if study.terminal_result_record_id:
            return study
        if study.state == "ANALYZING":
            run = self.workflows.get_workflow_run(study.run_id)
            if run.status.value == "running":
                return study
        if study.state != "READY_TO_ANALYZE" or not study.weight_approval_id:
            raise QuantitativeUiError("Current approved WeightSet is required before analysis")
        dataset, codebook = self._dataset(study)
        qc = self.state.load(study.qc_record_id or "", project_id=study.project_id, expected_type=QualityControlRun)
        weights = self.state.load(study.weight_set_record_id or "", project_id=study.project_id, expected_type=WeightSet)
        approvals = QuantitativeApprovalService(self.state, self.digest)
        approvals.require_current(study.qc_approval_id or "", project_id=study.project_id, subject_fingerprint=qc.fingerprint)
        approvals.require_current(study.weight_approval_id, project_id=study.project_id, subject_fingerprint=weights.reproducibility_fingerprint)
        run = self.workflows.get_workflow_run(study.run_id)
        if run.is_terminal:
            snapshots = self.state.list_for_run(study.run_id, project_id=study.project_id, expected_type=QuantitativeTerminalResult)
            if not snapshots: raise QuantitativeUiError("Terminal workflow authority is missing")
            record = self._terminal_record_id(study)
            return self._save(replace(study, state="COMPLETED", terminal_result_record_id=record))
        if run.status.value != "paused":
            raise QuantitativeUiError("Quantitative workflow is not awaiting authorized activation")
        safe = {
            "dataset_record_id": study.dataset_record_id or "", "codebook_record_id": study.codebook_record_id or "",
            "dataset_version_id": dataset.version_id, "dataset_fingerprint": dataset.dataset_fingerprint,
            "qc_record_id": study.qc_record_id or "", "qc_fingerprint": qc.fingerprint,
            "qc_approval_id": study.qc_approval_id or "", "cleaning_status": "CLEANED" if dataset.parent_version_id else "NOT_REQUIRED",
            "weight_set_record_id": study.weight_set_record_id or "", "weight_set_id": weights.weight_set_id,
            "weight_set_fingerprint": weights.reproducibility_fingerprint, "weight_approval_id": study.weight_approval_id,
        }
        if self.durable_workflow_service is not None:
            self.durable_workflow_service.activate_paused_run(
                study.run_id,
                shared_state={QUANTITATIVE_SAFE_STATE_KEY: safe},
                completed_task_definition_ids=tuple(
                    task.definition_id for task in run.tasks[:5]
                ),
            )
            return self._save(replace(study, state="ANALYZING"))
        run.resume()
        for task in run.tasks[:5]:
            if not task.is_terminal:
                task.ready(); task.start(); task.complete()
        service = self.stage_service_factory.create(
            project_id=study.project_id,
            run_id=study.run_id,
            safe_state=safe,
        )
        try:
            context = self._run_engine(study, run, service, safe)
            if not run.is_terminal or run.status.value != "completed":
                raise QuantitativeUiError("Quantitative workflow did not reach a terminal result")
            terminal_record_id = context.shared_state[QUANTITATIVE_SAFE_STATE_KEY]["terminal_result_record_id"]
            self.workflows.save_workflow_run(run, expected_version=self.workflows.get_workflow_run_version(run.id),
                                             task_results={
                                                 QUANTITATIVE_SAFE_STATE_KEY: context.shared_state[QUANTITATIVE_SAFE_STATE_KEY],
                                                 "_run_usage_summary": context.shared_state.get("run_usage_summary", {}),
                                             })
        except QuantitativeUiError:
            raise
        except _QuantitativeWorkflowExecutionFailure as exc:
            failed_context = exc.context
            safe_results = {
                QUANTITATIVE_SAFE_STATE_KEY: failed_context.shared_state.get(
                    QUANTITATIVE_SAFE_STATE_KEY, safe
                ),
                "_run_usage_summary": failed_context.shared_state.get(
                    "run_usage_summary", {}
                ),
                "quantitative_generation_status": "GENERATION_FAILED",
            }
            self.workflows.save_workflow_run(
                run,
                expected_version=self.workflows.get_workflow_run_version(run.id),
                task_results=safe_results,
            )
            raise QuantitativeUiError("Quantitative workflow failed safely") from None
        except Exception as exc:
            raise QuantitativeUiError("Quantitative workflow failed safely") from exc
        return self._save(replace(study, state="COMPLETED", terminal_result_record_id=terminal_record_id))

    def result_projection(self, study_id: str, *, owner_id: str) -> dict[str, Any]:
        study = self.get(study_id, owner_id=owner_id)
        if not study.terminal_result_record_id:
            raise QuantitativeUiError("Quantitative result is not available")
        from domain.quantitative.analysis import StatisticalResult, StatisticalTable
        from domain.quantitative.finding import QuantitativeFindingGenerationResult
        from domain.quantitative.insight import QuantitativeInsightGenerationResult
        from domain.quantitative.report import QuantitativeReportCompositionResult
        terminal = self.state.load(study.terminal_result_record_id, project_id=study.project_id, expected_type=QuantitativeTerminalResult)
        records = self.state.list_for_run(study.run_id, project_id=study.project_id)
        stats = tuple(item for item in records if isinstance(item, StatisticalResult))
        tables = tuple(item for item in records if isinstance(item, StatisticalTable))
        findings = next(item for item in records if isinstance(item, QuantitativeFindingGenerationResult))
        insights = next(item for item in records if isinstance(item, QuantitativeInsightGenerationResult))
        report = next(item for item in records if isinstance(item, QuantitativeReportCompositionResult))
        task_results = self.workflows.get_task_results(study.run_id)
        return {"study_id":study.study_id, "project_id":study.project_id, "run_id":study.run_id,
                "terminal_result_id":terminal.result_id, "terminal_status":terminal.terminal_outcome.value,
                "statistics":tuple({"result_id":item.result_id,"statistic_type":item.statistic_type,"value":str(item.value),
                                    "variable_id":item.variable_id,"weighting":item.weighting_status,"unweighted_n":item.unweighted_n,
                                    "weighted_base":str(item.weighted_base) if item.weighted_base is not None else None} for item in stats),
                "tables":tuple({"table_id":item.table_id,"orientation":item.percentage_orientation,
                                "result_ids":item.ordered_result_ids} for item in tables),
                "findings":{"accepted":tuple({"id":item.finding_id,"text":item.text} for item in findings.accepted_findings),
                            "rejected":tuple({"reason":item.reason} for item in findings.rejected_findings)},
                "insights":{"accepted":tuple({"id":item.insight_id,"text":item.insight_text} for item in insights.accepted_insights),
                            "rejected":tuple({"reason":item.reason} for item in insights.rejected_insights)},
                "report":{"id":report.accepted_report.report_id,"title":report.accepted_report.title,
                          "sections":tuple({"title":item.title,"narrative":item.narrative} for item in report.accepted_report.sections)},
                "limitations":terminal.limitations,
                "llm_usage":task_results.get("_run_usage_summary", {})}

    def _run_engine(self, study, run, service, safe):
        from application.workflow_engine import WorkflowEngine
        from application.task_scheduler import TaskScheduler
        from application.task_executor import TaskExecutor
        from application.task_lifecycle_manager import TaskLifecycleManager
        from application.runtime.workflow_completion_policy import WorkflowCompletionPolicy
        from runtime.workflow_context import WorkflowContext
        class Resolver:
            def resolve(self, task): return QuantitativeStageExecutor()
        context=WorkflowContext(project=self.projects.get_project(study.project_id),workflow_template=build_quantitative_workflow_template(),workflow_run=run,services={QUANTITATIVE_STAGE_SERVICE_KEY:service},shared_state={QUANTITATIVE_SAFE_STATE_KEY:safe})
        try:
            return WorkflowEngine(TaskScheduler(),TaskExecutor(Resolver(),TaskLifecycleManager()),WorkflowCompletionPolicy()).run(context)
        except Exception:
            raise _QuantitativeWorkflowExecutionFailure(context) from None

    def _terminal_record_id(self, study):
        records=self.state.list_for_run(study.run_id,project_id=study.project_id,expected_type=QuantitativeTerminalResult)
        terminal=max(records,key=lambda item:item.result_id)
        all_records=self.state._repository.list_for_run(study.run_id,project_id=study.project_id)
        return next(item.record_id for item in all_records if item.authority_fingerprint==terminal.fingerprint)

    def _require_setup_paused(self, study: QuantitativeStudyProjection) -> None:
        if self.workflows.get_workflow_run(study.run_id).status.value != "paused":
            raise QuantitativeUiError(
                "Quantitative setup is unavailable for the current execution state"
            )

    def _dataset(self, study: QuantitativeStudyProjection) -> tuple[DatasetVersion, CodebookVersion]:
        if not study.dataset_record_id or not study.codebook_record_id:
            raise QuantitativeUiError("Dataset has not been imported")
        return (self.state.load(study.dataset_record_id, project_id=study.project_id, expected_type=DatasetVersion),
                self.state.load(study.codebook_record_id, project_id=study.project_id, expected_type=CodebookVersion))

    def _save(self, study: QuantitativeStudyProjection) -> QuantitativeStudyProjection:
        updated = replace(study, revision=study.revision + 1)
        self._studies[study.study_id] = updated
        return self._persist_study(updated)

    def _persist_study(self, study: QuantitativeStudyProjection) -> QuantitativeStudyProjection:
        from application.quantitative.fingerprints import canonical_digest
        payload = {key: value for key, value in study.__dict__.items() if key != "fingerprint"}
        authoritative = replace(study, fingerprint=canonical_digest(payload, digest_provider=self.digest))
        self._studies[study.study_id] = authoritative
        self.state.persist(authoritative, record_id=f"{study.run_id}:ui-study:{study.revision}:{authoritative.fingerprint}",
                           project_id=study.project_id, run_id=study.run_id)
        return authoritative

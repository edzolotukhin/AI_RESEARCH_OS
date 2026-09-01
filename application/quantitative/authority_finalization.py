from __future__ import annotations

from dataclasses import asdict, dataclass

from application.quantitative.fingerprints import canonical_digest
from application.quantitative.state_persistence import authority_fingerprint
from application.quantitative.research_design_authority import resolve_study_weighting_mode
from application.quantitative.workflow import (
    QUANTITATIVE_SAFE_STATE_KEY,
    validate_safe_workflow_state,
)
from domain.quantitative.authority_finalization import (
    AUTHORITY_FINALIZATION_METHOD_VERSION,
    QuantitativeFinalizedStudyProjection,
)
from domain.quantitative.dataset import CodebookVersion, DatasetVersion
from domain.quantitative.insight_lineage import DesignAwareInsightControlledAbsence
from domain.quantitative.report_lineage import DesignAwareReportControlledAbsence
from domain.quantitative.research_question_coverage import QuantitativeAuthorityReference
from domain.quantitative.workflow import QuantitativeTerminalOutcome, QuantitativeTerminalResult
from domain.quantitative.research_design_authority import StudyWeightingMode
from domain.workflow_status import WorkflowStatus


class QuantitativeAuthorityFinalizationError(ValueError):
    pass


@dataclass(frozen=True)
class QuantitativeAuthorityFinalizationInput:
    project_id: str
    run_id: str
    terminal_result_record_id: str
    source_brief: QuantitativeAuthorityReference
    research_design: QuantitativeAuthorityReference
    questionnaire: QuantitativeAuthorityReference
    reconciliation: QuantitativeAuthorityReference
    analysis_plan: QuantitativeAuthorityReference
    analysis_execution: tuple[QuantitativeAuthorityReference, ...]
    finding_authority: tuple[QuantitativeAuthorityReference, ...]
    insight_authority: tuple[QuantitativeAuthorityReference, ...]
    report_authority: tuple[QuantitativeAuthorityReference, ...]
    research_question_authorities: tuple[QuantitativeAuthorityReference, ...]
    objective_authorities: tuple[QuantitativeAuthorityReference, ...]
    dataset: QuantitativeAuthorityReference
    codebook: QuantitativeAuthorityReference
    qc_authority: QuantitativeAuthorityReference
    weight_set_authorities: tuple[QuantitativeAuthorityReference, ...] = ()
    controlled_absences: tuple[QuantitativeAuthorityReference, ...] = ()
    execution_mode: str = "DESIGN_AWARE_EXECUTION"


class QuantitativeAuthorityFinalizationService:
    """Provider-free production transition from terminal workflow to Q2 authority."""

    _TERMINAL_OUTCOMES = {
        QuantitativeTerminalOutcome.COMPLETED,
        QuantitativeTerminalOutcome.COMPLETED_WITH_NO_SUPPORTED_FINDINGS,
        QuantitativeTerminalOutcome.COMPLETED_WITH_NO_SUPPORTED_INSIGHTS,
        QuantitativeTerminalOutcome.COMPLETED_WITH_NO_SUPPORTED_REPORT,
    }

    def __init__(self, *, project_service, workflow_service, state_service,
                 authority_chain_service, authority_chain_selection_service,
                 research_design_service, questionnaire_service,
                 reconciliation_service, analysis_plan_service,
                 research_question_coverage_service, objective_coverage_service,
                 digest_provider):
        self._projects = project_service
        self._workflows = workflow_service
        self._state = state_service
        self._chains = authority_chain_service
        self._selections = authority_chain_selection_service
        self._designs = research_design_service
        self._questionnaires = questionnaire_service
        self._reconciliations = reconciliation_service
        self._plans = analysis_plan_service
        self._questions = research_question_coverage_service
        self._objectives = objective_coverage_service
        self._digest = digest_provider

    def finalize(self, request: QuantitativeAuthorityFinalizationInput, *,
                 created_at: str, created_by: str,
                 supersedes_selection_id: str | None = None):
        terminal = self._preflight(request)
        manifest = self._chains.create_manifest(
            project_id=request.project_id, run_id=request.run_id,
            source_brief=request.source_brief, research_design=request.research_design,
            questionnaire=request.questionnaire, reconciliation=request.reconciliation,
            analysis_plan=request.analysis_plan, analysis_execution=request.analysis_execution,
            finding_authority=request.finding_authority,
            insight_authority=request.insight_authority,
            report_authority=request.report_authority,
            research_question_authorities=request.research_question_authorities,
            objective_authorities=request.objective_authorities,
            dataset=request.dataset, codebook=request.codebook,
            qc_authority=request.qc_authority,
            weight_set_authorities=request.weight_set_authorities,
            controlled_absences=request.controlled_absences,
        )
        selection = self._selections.activate(
            project_id=request.project_id, run_id=request.run_id,
            manifest_id=manifest.manifest_id, created_at=created_at,
            created_by=created_by, supersedes_selection_id=supersedes_selection_id,
        )
        chain = self._selections.resolve_current_authority_chain(
            project_id=request.project_id, run_id=request.run_id,
        )
        return self._projection(terminal, selection, chain)

    def resolve_current(self, *, project_id: str, run_id: str):
        self._scope(project_id, run_id)
        selection, chain = self._selections.resolve_current_selection(
            project_id=project_id, run_id=run_id,
        )
        dataset_ref = self._one(chain.ordered_authorities, "DATASET")
        dataset = self._state.load(dataset_ref.authority_id, project_id=project_id)
        dataset_version_id = getattr(dataset, "version_id", dataset_ref.authority_id)
        results = self._workflows.get_task_results(run_id)
        safe_state = validate_safe_workflow_state(
            results.get(QUANTITATIVE_SAFE_STATE_KEY, {})
        )
        terminal_record_id = safe_state.get("terminal_result_record_id")
        if not terminal_record_id:
            raise QuantitativeAuthorityFinalizationError(
                "completed WorkflowRun has no durable terminal record reference"
            )
        terminal = self._state.load(
            terminal_record_id, project_id=project_id,
            expected_type=QuantitativeTerminalResult,
        )
        if (
            terminal.run_id != run_id
            or terminal.dataset_version_id != dataset_version_id
            or terminal.dataset_fingerprint != dataset_ref.authority_fingerprint
        ):
            raise QuantitativeAuthorityFinalizationError(
                "completed WorkflowRun terminal authority mismatch"
            )
        request = self._request_from_chain(
            chain, terminal_result_record_id=terminal_record_id,
        )
        terminal = self._preflight(request)
        return self._projection(terminal, selection, chain)

    def _request_from_chain(self, chain, *, terminal_result_record_id):
        refs = chain.ordered_authorities
        controlled = {
            (item.authority_kind, item.authority_id) for item in chain.controlled_absences
        }

        def group(prefix):
            return tuple(
                item for item in refs
                if item.authority_kind.startswith(prefix)
                and (item.authority_kind, item.authority_id) not in controlled
            )

        return QuantitativeAuthorityFinalizationInput(
            project_id=chain.project_id,
            run_id=chain.run_id,
            terminal_result_record_id=terminal_result_record_id,
            source_brief=self._one(refs, "QZ_BRIEF"),
            research_design=self._one(refs, "QZ_DESIGN"),
            questionnaire=self._one(refs, "RA_QUESTIONNAIRE"),
            reconciliation=self._one(refs, "RB_RECONCILIATION"),
            analysis_plan=self._one(refs, "RC_PLAN"),
            analysis_execution=group("RD_"),
            finding_authority=group("RE_"),
            insight_authority=group("RF_"),
            report_authority=group("RG_"),
            research_question_authorities=chain.research_question_authorities,
            objective_authorities=chain.objective_authorities,
            dataset=self._one(refs, "DATASET"),
            codebook=self._one(refs, "CODEBOOK"),
            qc_authority=self._one(refs, "QC_APPROVAL"),
            weight_set_authorities=group("WEIGHT_SET"),
            controlled_absences=chain.controlled_absences,
        )

    def reconstruct_backward(self, *, project_id: str, run_id: str, objective_authority_id: str):
        self.resolve_current(project_id=project_id, run_id=run_id)
        selection, chain = self._selections.resolve_current_selection(project_id=project_id, run_id=run_id)
        if not any(x.authority_id == objective_authority_id for x in chain.objective_authorities):
            raise QuantitativeAuthorityFinalizationError("Objective authority is not bound to the finalized current chain")
        return chain
    def _preflight(self, request):
        if request.execution_mode != "DESIGN_AWARE_EXECUTION":
            raise QuantitativeAuthorityFinalizationError(
                "dataset-only execution is not design-aware finalization"
            )
        self._scope(request.project_id, request.run_id)
        terminal = self._state.load(
            request.terminal_result_record_id, project_id=request.project_id,
            expected_type=QuantitativeTerminalResult,
        )
        if terminal.project_id != request.project_id or terminal.run_id != request.run_id:
            raise QuantitativeAuthorityFinalizationError("terminal authority has wrong project/run")
        if terminal.execution_status != "COMPLETED" or terminal.terminal_outcome not in self._TERMINAL_OUTCOMES:
            raise QuantitativeAuthorityFinalizationError("workflow terminal outcome is not finalizable")
        dataset = self._state.load(request.dataset.authority_id, project_id=request.project_id)
        dataset_version_id = getattr(dataset, "version_id", request.dataset.authority_id)
        if (dataset_version_id, request.dataset.authority_fingerprint) != (
            terminal.dataset_version_id, terminal.dataset_fingerprint
        ):
            raise QuantitativeAuthorityFinalizationError("terminal Dataset authority mismatch")
        unweighted_refs = tuple(
            ref for ref in request.controlled_absences
            if ref.authority_kind == "WEIGHTING_UNWEIGHTED"
        )
        if terminal.weighting_mode == StudyWeightingMode.WEIGHTED.value:
            if unweighted_refs or not request.weight_set_authorities:
                raise QuantitativeAuthorityFinalizationError("weighted terminal lacks exact WeightSet authority")
            matches = []
            for ref in request.weight_set_authorities:
                weight = self._state.load(ref.authority_id, project_id=request.project_id)
                matches.append((getattr(weight, "weight_set_id", ref.authority_id), ref.authority_fingerprint))
            if (terminal.weight_set_id, terminal.weight_set_fingerprint) not in matches:
                raise QuantitativeAuthorityFinalizationError("terminal WeightSet authority mismatch")
        elif terminal.weighting_mode == StudyWeightingMode.UNWEIGHTED.value:
            if request.weight_set_authorities or terminal.weight_set_id is not None or terminal.weight_set_fingerprint is not None or terminal.weight_approval_id is not None:
                raise QuantitativeAuthorityFinalizationError("unweighted terminal carries WeightSet authority")
            if len(unweighted_refs) != 1 or unweighted_refs[0].authority_fingerprint != terminal.weighting_authority_fingerprint:
                raise QuantitativeAuthorityFinalizationError("explicit unweighted terminal authority is missing")
        else:
            raise QuantitativeAuthorityFinalizationError("terminal weighting authority is unresolved")
        if not request.analysis_execution or not request.research_question_authorities:
            raise QuantitativeAuthorityFinalizationError("required RD/RH authority is missing")
        self._validate_controlled_downstream(request, terminal)
        self._validate_current_upstream(request, terminal, dataset)
        return terminal

    def _validate_current_upstream(self, request, terminal, dataset):
        codebook = self._state.load(request.codebook.authority_id, project_id=request.project_id)
        datasets = self._state.list_for_run(request.run_id, project_id=request.project_id, expected_type=DatasetVersion)
        if datasets:
            parents = {item.parent_version_id for item in datasets if item.parent_version_id}
            heads = tuple(item for item in datasets if item.version_id not in parents)
            if len(heads) != 1 or heads[0] != dataset:
                raise QuantitativeAuthorityFinalizationError("historical or ambiguous Dataset authority cannot be finalized")
            codebooks = tuple(item for item in self._state.list_for_run(request.run_id, project_id=request.project_id, expected_type=CodebookVersion) if item.codebook_version_id == dataset.codebook_version_id)
            if len(codebooks) != 1 or codebooks[0] != codebook:
                raise QuantitativeAuthorityFinalizationError("historical or ambiguous Codebook authority cannot be finalized")
        current_design = self._designs.resolve_current_approved(
            project_id=request.project_id, run_id=request.run_id,
        )
        self._require_current_reference(request.research_design, current_design, "QZ")
        current_weighting_mode = None
        if hasattr(current_design, "methodology_intent"):
            current_weighting_mode = resolve_study_weighting_mode(current_design)
        if current_weighting_mode is not None and (
            current_weighting_mode is StudyWeightingMode.UNRESOLVED
            or terminal.weighting_mode != current_weighting_mode.value
            or terminal.weighting_authority_fingerprint != current_design.fingerprint
        ):
            raise QuantitativeAuthorityFinalizationError("terminal weighting authority is stale")
        if current_weighting_mode is StudyWeightingMode.UNWEIGHTED:
            unweighted_refs = tuple(
                ref for ref in request.controlled_absences
                if ref.authority_kind == "WEIGHTING_UNWEIGHTED"
            )
            if len(unweighted_refs) != 1 or (
                unweighted_refs[0].authority_id,
                unweighted_refs[0].authority_fingerprint,
            ) != (current_design.version_id, current_design.fingerprint):
                raise QuantitativeAuthorityFinalizationError("current explicit unweighted authority mismatch")
        source_version_id = getattr(current_design, "source_brief_version_id", None)
        source_fingerprint = getattr(current_design, "source_brief_fingerprint", None)
        if source_version_id is not None:
            source = self._state.load(request.source_brief.authority_id, project_id=request.project_id)
            if (getattr(source, "version_id", request.source_brief.authority_id), authority_fingerprint(source)) != (source_version_id, source_fingerprint):
                raise QuantitativeAuthorityFinalizationError("current QZ source Brief authority mismatch")
        current_questionnaire = self._questionnaires.resolve_current_approved(
            project_id=request.project_id, run_id=request.run_id,
        )
        self._require_current_reference(request.questionnaire, current_questionnaire, "RA")
        current_reconciliation = self._reconciliations.resolve_current_accepted(
            project_id=request.project_id, run_id=request.run_id,
            dataset=dataset, codebook=codebook,
        )
        self._require_current_reference(request.reconciliation, current_reconciliation, "RB")
        weight_values = tuple(
            self._state.load(ref.authority_id, project_id=request.project_id)
            for ref in request.weight_set_authorities
        )
        approvals = tuple(
            item for item in self._state.list_for_run(request.run_id, project_id=request.project_id)
            if getattr(getattr(item, "state", None), "value", None) == "APPROVED"
            and hasattr(item, "weight_set_id")
        )
        candidate_plan = self._state.load(request.analysis_plan.authority_id, project_id=request.project_id)
        weight_pairs = []
        for planned in getattr(candidate_plan, "planned_analyses", ()):
            binding = getattr(planned, "weight_set_binding", None)
            if binding is None:
                continue
            weight = next((item for item in weight_values if getattr(item, "weight_set_id", None) == binding.weight_set_id), None)
            approval = next((item for item in approvals if getattr(item, "weight_set_id", None) == binding.weight_set_id), None)
            if weight is not None and approval is not None:
                weight_pairs.append((planned.planned_analysis_id, (weight, approval)))
        current_plan = self._plans.resolve_current_approved(
            project_id=request.project_id, run_id=request.run_id,
            dataset=dataset, codebook=codebook, weight_sets=tuple(weight_pairs),
        )
        self._require_current_reference(request.analysis_plan, current_plan, "RC")
        self._validate_current_downstream(request, current_design, current_plan, dataset, codebook)
        if getattr(current_plan, "dataset_fingerprint", terminal.dataset_fingerprint) != terminal.dataset_fingerprint:
            raise QuantitativeAuthorityFinalizationError("current RC Dataset authority mismatch")

    def _validate_current_downstream(self, request, design, plan, dataset, codebook):
        design_weighting_mode = (
            resolve_study_weighting_mode(design)
            if hasattr(design, "methodology_intent") else None
        )
        rd_values = tuple(self._state.load(ref.authority_id, project_id=request.project_id) for ref in request.analysis_execution)
        rd_manifests = tuple(
            item for item in rd_values
            if hasattr(item, "execution_mode") and hasattr(item, "manifest_id")
        )
        rd_fingerprints = {authority_fingerprint(item) for item in rd_manifests}
        rd_parents = {
            item.parent_manifest_id for item in rd_manifests
            if getattr(item, "parent_manifest_id", None)
        }
        rd_heads = tuple(item for item in rd_manifests if item.manifest_id not in rd_parents)
        if rd_manifests:
            if len(rd_heads) != 1:
                raise QuantitativeAuthorityFinalizationError("historical or ambiguous RD authority cannot be finalized")
            rd = rd_heads[0]
            if (rd.plan_version_id, rd.plan_fingerprint, rd.dataset_version_id, rd.dataset_fingerprint,
                rd.codebook_version_id, rd.codebook_fingerprint) != (
                plan.version_id, plan.fingerprint, dataset.version_id, dataset.dataset_fingerprint,
                codebook.codebook_version_id, codebook.fingerprint):
                raise QuantitativeAuthorityFinalizationError("stale RD authority cannot be finalized")
            if design_weighting_mode is not None and (
                rd.weighting_mode != design_weighting_mode.value
                or rd.weighting_authority_fingerprint != design.fingerprint
            ):
                raise QuantitativeAuthorityFinalizationError("stale RD weighting authority cannot be finalized")
        for label, refs in (("RE", request.finding_authority), ("RF", request.insight_authority),
                            ("RG", request.report_authority), ("CONTROLLED_ABSENCE", request.controlled_absences)):
            for ref in refs:
                value = self._state.load(ref.authority_id, project_id=request.project_id)
                rc_fingerprint = getattr(value, "rc_plan_fingerprint", None)
                rd_fingerprint = getattr(value, "rd_execution_manifest_fingerprint", None)
                if rc_fingerprint is not None and rc_fingerprint != plan.fingerprint:
                    raise QuantitativeAuthorityFinalizationError(f"stale {label} RC binding cannot be finalized")
                if rd_fingerprint is not None and rd_fingerprint not in rd_fingerprints:
                    raise QuantitativeAuthorityFinalizationError(f"stale {label} RD binding cannot be finalized")
        for ref in request.research_question_authorities:
            value = self._state.load(ref.authority_id, project_id=request.project_id)
            research_question_id = getattr(value, "research_question_id", None)
            if research_question_id is None:
                continue
            projection = self._questions.resolve_current_approved(
                project_id=request.project_id, run_id=request.run_id,
                research_question_id=research_question_id,
                upstream_authority_fingerprints=value.upstream_authority_fingerprints,
            )
            if projection.assessment_fingerprint != authority_fingerprint(value):
                raise QuantitativeAuthorityFinalizationError("historical or stale RH authority cannot be finalized")
        for ref in request.objective_authorities:
            value = self._state.load(ref.authority_id, project_id=request.project_id)
            objective_id = getattr(value, "objective_id", None)
            if objective_id is None:
                continue
            projection = self._objectives.get_approved_projection(
                project_id=request.project_id, run_id=request.run_id, objective_id=objective_id,
            )
            if projection.assessment_fingerprint != authority_fingerprint(value):
                raise QuantitativeAuthorityFinalizationError("historical or stale RI authority cannot be finalized")
    def _require_current_reference(self, ref, current, label):
        exact = self._state.load(ref.authority_id, project_id=getattr(current, "project_id", ""))
        if exact != current or authority_fingerprint(exact) != ref.authority_fingerprint:
            raise QuantitativeAuthorityFinalizationError(f"historical or stale {label} authority cannot be finalized")
    def _scope(self, project_id, run_id):
        self._projects.get_project(project_id)
        run = self._workflows.get_workflow_run(run_id)
        if run.project_id != project_id:
            raise QuantitativeAuthorityFinalizationError("WorkflowRun has wrong Project")
        if run.status is not WorkflowStatus.COMPLETED:
            raise QuantitativeAuthorityFinalizationError("WorkflowRun is not successfully terminal")

    def _validate_controlled_downstream(self, request, terminal):
        absence_kinds = {item.authority_kind for item in request.controlled_absences}
        has_rf_absence = any(kind.startswith("RF_") for kind in absence_kinds)
        has_rg_absence = any(kind.startswith("RG_") for kind in absence_kinds)
        typed = tuple(
            self._state.load(item.authority_id, project_id=request.project_id)
            for item in request.controlled_absences
        )
        for ref, value in zip(request.controlled_absences, typed):
            if isinstance(value, DesignAwareInsightControlledAbsence):
                if (
                    ref.authority_kind != "RF_CONTROLLED_ABSENCE"
                    or terminal.terminal_outcome
                    is not QuantitativeTerminalOutcome.COMPLETED_WITH_NO_SUPPORTED_FINDINGS
                    or request.insight_authority
                ):
                    raise QuantitativeAuthorityFinalizationError(
                        "contradictory RF controlled-absence authority"
                    )
            if isinstance(value, DesignAwareReportControlledAbsence):
                if (
                    ref.authority_kind != "RG_CONTROLLED_ABSENCE"
                    or terminal.terminal_outcome
                    is not QuantitativeTerminalOutcome.COMPLETED_WITH_NO_SUPPORTED_FINDINGS
                    or request.report_authority
                ):
                    raise QuantitativeAuthorityFinalizationError(
                        "contradictory RG controlled-absence authority"
                    )
        if not request.finding_authority:
            raise QuantitativeAuthorityFinalizationError("required RE authority is missing")
        if terminal.terminal_outcome is QuantitativeTerminalOutcome.COMPLETED:
            if not request.insight_authority or not request.report_authority:
                raise QuantitativeAuthorityFinalizationError("completed run lacks RF/RG authority")
        elif terminal.terminal_outcome is QuantitativeTerminalOutcome.COMPLETED_WITH_NO_SUPPORTED_FINDINGS:
            if request.insight_authority or request.report_authority or not (has_rf_absence and has_rg_absence):
                raise QuantitativeAuthorityFinalizationError("invalid controlled no-Finding authority")
        elif terminal.terminal_outcome is QuantitativeTerminalOutcome.COMPLETED_WITH_NO_SUPPORTED_INSIGHTS:
            if request.report_authority or not (request.insight_authority or has_rf_absence) or not has_rg_absence:
                raise QuantitativeAuthorityFinalizationError("invalid controlled no-Insight authority")
        elif terminal.terminal_outcome is QuantitativeTerminalOutcome.COMPLETED_WITH_NO_SUPPORTED_REPORT:
            if not request.insight_authority or (not request.report_authority and not has_rg_absence):
                raise QuantitativeAuthorityFinalizationError("invalid controlled no-Report authority")

    def _projection(self, terminal, selection, chain):
        qz = self._one(chain.ordered_authorities, "QZ_DESIGN")
        brief = self._one(chain.ordered_authorities, "QZ_BRIEF")
        rh = tuple(sorted((x.authority_id, x.authority_fingerprint, self._status(x, chain.project_id))
                          for x in chain.research_question_authorities))
        ri = tuple(sorted((x.authority_id, x.authority_fingerprint)
                          for x in chain.objective_authorities))
        absences = tuple(sorted((x.authority_kind, x.authority_id, x.authority_fingerprint)
                                for x in chain.controlled_absences))
        limitations = tuple(sorted(set(terminal.limitations)))
        payload = {
            "contract": "RL_FINALIZED_STUDY_PROJECTION_V1",
            "project": chain.project_id, "run": chain.run_id,
            "terminal": terminal.result_id, "terminal_fingerprint": authority_fingerprint(terminal),
            "terminal_outcome": terminal.terminal_outcome.value,
            "manifest": chain.manifest_id, "manifest_fingerprint": chain.manifest_fingerprint,
            "selection": selection.selection_id, "selection_fingerprint": selection.fingerprint,
            "qz": asdict(qz), "brief": asdict(brief), "rh": rh, "ri": ri,
            "absences": absences, "limitations": limitations,
            "method": AUTHORITY_FINALIZATION_METHOD_VERSION,
        }
        fingerprint = canonical_digest(payload, digest_provider=self._digest)
        return QuantitativeFinalizedStudyProjection(
            chain.project_id, chain.run_id, WorkflowStatus.COMPLETED.value,
            terminal.result_id, authority_fingerprint(terminal), terminal.terminal_outcome.value,
            qz.authority_id, qz.authority_fingerprint,
            brief.authority_id, brief.authority_fingerprint,
            chain.manifest_id, chain.manifest_fingerprint,
            selection.selection_id, selection.fingerprint, rh, ri, absences, (), limitations,
            AUTHORITY_FINALIZATION_METHOD_VERSION, fingerprint,
        )

    def _status(self, ref, project_id):
        value = self._state.load(ref.authority_id, project_id=project_id)
        status = getattr(value, "decision", None) or getattr(value, "status", None)
        return getattr(status, "value", status) or "BOUND"

    @staticmethod
    def _one(refs, kind):
        values = tuple(x for x in refs if x.authority_kind == kind)
        if len(values) != 1:
            raise QuantitativeAuthorityFinalizationError(f"exact {kind} authority is missing or ambiguous")
        return values[0]

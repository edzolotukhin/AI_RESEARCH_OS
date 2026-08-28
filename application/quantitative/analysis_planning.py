from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Mapping
from uuid import NAMESPACE_URL, uuid5

from application.quantitative.fingerprints import canonical_digest, canonical_scalar, fingerprint_analysis_specification
from application.quantitative.comparison_statistics import MEAN_METHOD, PROPORTION_METHOD
from domain.quantitative.analysis import AnalysisSpecification, CrossTabAnalysisSpecification, NumericAnalysisSpecification, NpsAnalysisSpecification, CustomIndexAnalysisSpecification, ComparisonSpecification
from domain.quantitative.analysis_plan import *
from domain.quantitative.dataset import PiiClassification, VariableType
from domain.quantitative.measurement_reconciliation import ReconciliationMatchStatus, DataAvailabilityStatus
from domain.quantitative.quality import DatasetQualityAssessment, DatasetQualityState
from domain.quantitative.research_design_authority import RequirementObligation
from domain.quantitative.weighting import WeightApprovalState, WeightSet, WeightSetApproval

class QuantitativeAnalysisPlanError(ValueError): pass

class QuantitativeAnalysisPlanService:
    def __init__(self,*,repository,research_design_service,questionnaire_service,reconciliation_service,digest_provider):
        self._repository=repository; self._designs=research_design_service; self._questionnaires=questionnaire_service; self._reconciliations=reconciliation_service; self._digest=digest_provider

    def create_draft(self,*,plan_id,version_id,project_id,run_id,dataset,codebook,planned_analyses,planned_comparisons=(),coverage_declarations=(),weight_sets:Mapping[str,tuple[WeightSet,WeightSetApproval]]|None=None,assumptions=(),limitations=(),created_at,created_by,_version_sequence=1,_parent_version_id=None):
        design,questionnaire,schema,reconciliation,availability=self._authority(project_id,run_id,dataset,codebook)
        analyses=self._validate_analyses(tuple(planned_analyses),design,schema,reconciliation,codebook,dataset,weight_sets or {})
        comparisons=self._validate_comparisons(tuple(planned_comparisons),analyses,design)
        declarations=tuple(coverage_declarations); self._validate_declarations(declarations,design)
        content=self._content(plan_id,project_id,design,questionnaire,schema,reconciliation,dataset,codebook,analyses,comparisons,declarations,tuple(assumptions),tuple(limitations))
        content_fp=canonical_digest(content,digest_provider=self._digest)
        coverage=self._coverage(version_id,project_id,content_fp,design,questionnaire,reconciliation,availability,analyses,declarations)
        plan_fp=canonical_digest({"contract":"RC_PLAN_V1","content":content,"coverage":coverage.fingerprint},digest_provider=self._digest)
        value=QuantitativeAnalysisPlanVersion(plan_id,version_id,_version_sequence,project_id,"QUANTITATIVE",design.version_id,design.fingerprint,questionnaire.version_id,questionnaire.fingerprint,schema.fingerprint,reconciliation.version_id,reconciliation.fingerprint,dataset.version_id,dataset.dataset_fingerprint,dataset.data_fingerprint,dataset.schema_fingerprint,codebook.codebook_version_id,codebook.fingerprint,analyses,comparisons,coverage.manifest_id,coverage.fingerprint,declarations,tuple(assumptions),tuple(limitations),_parent_version_id,AnalysisPlanLifecycle.DRAFT,None,plan_fp,created_at,created_by)
        self._repository.save_plan(value,run_id=run_id); self._repository.save_coverage(coverage,run_id=run_id); return value

    def revise(self,version_id,*,project_id,run_id,new_version_id,dataset,codebook,created_at,created_by,weight_sets=(),**changes):
        old=self._require(version_id,project_id); allowed={"planned_analyses","planned_comparisons","coverage_declarations","assumptions","limitations"}
        if set(changes)-allowed: raise QuantitativeAnalysisPlanError("unsupported Plan revision field")
        return self.create_draft(plan_id=old.plan_id,version_id=new_version_id,project_id=project_id,run_id=run_id,dataset=dataset,codebook=codebook,planned_analyses=changes.get("planned_analyses",old.planned_analyses),planned_comparisons=changes.get("planned_comparisons",old.planned_comparisons),coverage_declarations=changes.get("coverage_declarations",old.coverage_declarations),weight_sets=dict(weight_sets),assumptions=changes.get("assumptions",old.assumptions),limitations=changes.get("limitations",old.limitations),created_at=created_at,created_by=created_by,_version_sequence=old.version_sequence+1,_parent_version_id=old.version_id)

    def submit_for_review(self,version_id,*,project_id,run_id,new_version_id,actor_id,changed_at): return self._transition(version_id,project_id,run_id,new_version_id,actor_id,changed_at,AnalysisPlanLifecycle.IN_REVIEW)
    def approve(self,version_id,*,project_id,run_id,new_version_id,approval_id,expected_fingerprint,actor_id,decided_at,rationale,dataset,codebook,weight_sets=()):
        current=self._require(version_id,project_id)
        if current.lifecycle_status is not AnalysisPlanLifecycle.IN_REVIEW or current.fingerprint!=expected_fingerprint: raise QuantitativeAnalysisPlanError("Plan is not in review or approval fingerprint is stale")
        self._require_current(current,project_id,run_id,dataset,codebook,dict(weight_sets))
        coverage=self._repository.get_coverage(current.coverage_manifest_id,project_id=project_id)
        if coverage is None or coverage.fingerprint!=current.coverage_manifest_fingerprint: raise QuantitativeAnalysisPlanError("Plan coverage is stale")
        rationale=" ".join(rationale.split())
        if not rationale: raise QuantitativeAnalysisPlanError("approval rationale is required")
        approved=replace(current,version_id=new_version_id,version_sequence=current.version_sequence+1,parent_version_id=current.version_id,lifecycle_status=AnalysisPlanLifecycle.APPROVED,approval_reference=approval_id,created_at=decided_at,created_by=actor_id)
        coverage=replace(coverage,manifest_id=f"rc-coverage-{new_version_id}",plan_version_id=new_version_id)
        payload={"contract":"RC_APPROVAL_V1","project":project_id,"plan":approved.fingerprint,"version":new_version_id,"qz":approved.research_design_fingerprint,"ra":approved.questionnaire_fingerprint,"rb":approved.reconciliation_fingerprint,"dataset":approved.dataset_fingerprint,"codebook":approved.codebook_fingerprint,"weights":self._weight_fps(approved),"coverage":coverage.fingerprint,"actor":actor_id,"time":decided_at,"decision":"APPROVED","rationale":rationale}
        approval=QuantitativeAnalysisPlanApproval(approval_id,project_id,"QUANTITATIVE",new_version_id,approved.fingerprint,approved.research_design_fingerprint,approved.questionnaire_fingerprint,approved.reconciliation_fingerprint,approved.dataset_fingerprint,approved.codebook_fingerprint,self._weight_fps(approved),coverage.fingerprint,actor_id,decided_at,AnalysisPlanApprovalDecision.APPROVED,rationale,canonical_digest(payload,digest_provider=self._digest))
        approved=replace(approved,coverage_manifest_id=coverage.manifest_id,coverage_manifest_fingerprint=coverage.fingerprint)
        self._repository.save_plan(approved,run_id=run_id);self._repository.save_coverage(coverage,run_id=run_id);self._repository.save_approval(approval,run_id=run_id);return approved

    def reject(self,version_id,*,project_id,run_id,new_version_id,approval_id,expected_fingerprint,actor_id,decided_at,rationale):
        current=self._require(version_id,project_id)
        if current.lifecycle_status is not AnalysisPlanLifecycle.IN_REVIEW or current.fingerprint!=expected_fingerprint: raise QuantitativeAnalysisPlanError("Plan is not in review or fingerprint is stale")
        rejected=self._transition(version_id,project_id,run_id,new_version_id,actor_id,decided_at,AnalysisPlanLifecycle.REJECTED,approval_id)
        rationale=" ".join(rationale.split());
        if not rationale: raise QuantitativeAnalysisPlanError("rejection rationale is required")
        payload={"contract":"RC_APPROVAL_V1","plan":rejected.fingerprint,"decision":"REJECTED","actor":actor_id,"rationale":rationale}
        approval=QuantitativeAnalysisPlanApproval(approval_id,project_id,"QUANTITATIVE",rejected.version_id,rejected.fingerprint,rejected.research_design_fingerprint,rejected.questionnaire_fingerprint,rejected.reconciliation_fingerprint,rejected.dataset_fingerprint,rejected.codebook_fingerprint,self._weight_fps(rejected),rejected.coverage_manifest_fingerprint,actor_id,decided_at,AnalysisPlanApprovalDecision.REJECTED,rationale,canonical_digest(payload,digest_provider=self._digest));self._repository.save_approval(approval,run_id=run_id);return rejected
    def supersede(self,version_id,*,project_id,run_id,new_version_id,actor_id,changed_at):
        if self._require(version_id,project_id).lifecycle_status is not AnalysisPlanLifecycle.APPROVED: raise QuantitativeAnalysisPlanError("only approved Plan can be superseded")
        return self._transition(version_id,project_id,run_id,new_version_id,actor_id,changed_at,AnalysisPlanLifecycle.SUPERSEDED)

    def resolve_current_approved(
        self, *, project_id, run_id, dataset, codebook, weight_sets=(),
        weight_authorities=(),
    ):
        plans=self._repository.list_plans(project_id=project_id,run_id=run_id)
        if not plans or plans[-1].lifecycle_status is not AnalysisPlanLifecycle.APPROVED: raise QuantitativeAnalysisPlanError("no current approved Analysis Plan")
        value=plans[-1]
        bindings = dict(weight_sets)
        if weight_authorities:
            bindings = self._execution_weight_bindings(value, dict(weight_authorities))
        self._require_current(value,project_id,run_id,dataset,codebook,bindings);approval=self._repository.get_approval(value.approval_reference or "",project_id=project_id)
        if approval is None or approval.decision is not AnalysisPlanApprovalDecision.APPROVED or approval.plan_fingerprint!=value.fingerprint or approval.coverage_manifest_fingerprint!=value.coverage_manifest_fingerprint: raise QuantitativeAnalysisPlanError("Plan approval is missing or stale")
        return value
    def resolve_current_execution_authority(
        self, *, project_id, run_id, dataset, codebook, weight_authorities=()
    ):
        """Resolve current RC and its exact approved WeightSet bindings."""
        available = dict(weight_authorities)
        current = self.resolve_current_approved(
            project_id=project_id,
            run_id=run_id,
            dataset=dataset,
            codebook=codebook,
            weight_authorities=available,
        )
        return current, self._execution_weight_bindings(current, available)

    @staticmethod
    def _execution_weight_bindings(plan, available):
        bindings = {}
        for item in plan.planned_analyses:
            binding = item.weight_set_binding
            if binding is not None and binding.weight_set_id in available:
                bindings[item.planned_analysis_id] = available[binding.weight_set_id]
        return bindings

    def approved_projection(self,**kwargs):
        value=self.resolve_current_approved(**kwargs);coverage=self._repository.get_coverage(value.coverage_manifest_id,project_id=value.project_id)
        return ApprovedAnalysisPlanProjection(value.plan_id,value.version_id,value.fingerprint,(("qz",value.research_design_fingerprint),("ra",value.questionnaire_fingerprint),("rb",value.reconciliation_fingerprint),("dataset",value.dataset_fingerprint),("codebook",value.codebook_fingerprint)),tuple((x.planned_analysis_id,x.specification.statistic_family,x.specification_fingerprint,x.research_question_ids,x.analytical_requirement_ids,tuple((b.expected_variable_id,b.actual_variable_id,b.actual_variable_fingerprint) for b in x.variable_bindings)) for x in value.planned_analyses),tuple((x.planned_comparison_id,x.specification.method,x.precursor_analysis_ids) for x in value.planned_comparisons),tuple((x.requirement_id,x.status.value) for x in coverage.requirements),value.assumptions,value.limitations)
    def execution_projection(self,*,quality_assessment=None,**kwargs):
        dataset=kwargs.get("dataset")
        if not isinstance(quality_assessment,DatasetQualityAssessment) or not quality_assessment.current or quality_assessment.state is not DatasetQualityState.QC_APPROVED or not quality_assessment.approval_fingerprint or dataset is None or quality_assessment.dataset_version_id!=dataset.version_id or quality_assessment.dataset_fingerprint!=dataset.dataset_fingerprint:
            raise QuantitativeAnalysisPlanError("current fingerprint-bound QC authority is required for execution")
        value=self.resolve_current_approved(**kwargs); specs=tuple(x.specification for x in value.planned_analyses);comparisons=tuple(x.specification for x in value.planned_comparisons);fp=canonical_digest({"plan":value.fingerprint,"analyses":tuple(self._analysis_payload(x) for x in value.planned_analyses),"comparisons":tuple((x.planned_comparison_id,x.specification_fingerprint,x.precursor_analysis_ids,x.objective_ids,x.research_question_ids,x.analytical_requirement_ids,x.obligation,tuple((r.role,r.precursor_analysis_id,r.statistic_type,r.variable_id,r.group_variable_id,canonical_scalar(r.outcome_category),canonical_scalar(r.group_category),r.filter_definition) for r in x.result_role_selectors)) for x in value.planned_comparisons),"coverage":value.coverage_manifest_fingerprint,"qc_authority":quality_assessment.fingerprint},digest_provider=self._digest);return AnalysisExecutionProjection(value.plan_id,value.version_id,value.fingerprint,quality_assessment.fingerprint,value.coverage_manifest_id,value.coverage_manifest_fingerprint,value.planned_analyses,value.planned_comparisons,specs,comparisons,fp)
    def resolve_dataset_only(self,*,authority_id,project_id,run_id):
        limitation="Design-aware analysis-plan coverage is absent in dataset-only exploratory mode.";payload={"contract":"RC_DATASET_ONLY_V1","authority":authority_id,"project":project_id,"run":run_id,"status":"NO_DESIGN_AWARE_ANALYSIS_PLAN_AUTHORITY","limitation":limitation};value=DatasetOnlyAnalysisPlanAuthority(authority_id,project_id,run_id,"NO_DESIGN_AWARE_ANALYSIS_PLAN_AUTHORITY",limitation,canonical_digest(payload,digest_provider=self._digest));self._repository.save_dataset_only(value);return value

    def _authority(self,project_id,run_id,dataset,codebook):
        design=self._designs.resolve_current_approved(project_id=project_id,run_id=run_id);q=self._questionnaires.resolve_current_approved(project_id=project_id,run_id=run_id);schema=self._questionnaires.derive_expected_measurement_schema(q.version_id,project_id=project_id);r=self._reconciliations.resolve_current_accepted(project_id=project_id,run_id=run_id,dataset=dataset,codebook=codebook);availability=self._reconciliations._repository.get_availability(r.data_availability_manifest_id,project_id=project_id)
        if design.project_id!=project_id or q.research_design_version_id!=design.version_id or q.research_design_fingerprint!=design.fingerprint or r.questionnaire_version_id!=q.version_id or r.questionnaire_fingerprint!=q.fingerprint or r.expected_measurement_schema_fingerprint!=schema.fingerprint: raise QuantitativeAnalysisPlanError("upstream Quantitative authority is stale")
        return design,q,schema,r,availability
    def _validate_analyses(self,items,design,schema,r,codebook,dataset,weight_sets):
        if len({x.planned_analysis_id for x in items})!=len(items): raise QuantitativeAnalysisPlanError("duplicate PlannedAnalysis ID")
        rq={x.question_id:x for x in design.research_questions}; req={x.requirement_id:x for x in design.analytical_requirements}; objectives={x.objective_id for x in design.objectives}; expected={x.expected_variable_id:x for x in schema.variables}; outcomes={x.expected_variable_id:x for x in r.variable_outcomes}; actual={x.variable_id:x for x in codebook.variables}; result=[]
        for item in items:
            if not item.research_question_ids or not item.analytical_requirement_ids or any(x not in rq for x in item.research_question_ids) or any(x not in req for x in item.analytical_requirement_ids): raise QuantitativeAnalysisPlanError("missing or dangling design lineage")
            for rid in item.analytical_requirement_ids:
                if not set(item.research_question_ids).intersection(req[rid].research_question_ids): raise QuantitativeAnalysisPlanError("ResearchQuestion does not support AnalyticalRequirement")
            if any(x not in objectives for x in item.objective_ids): raise QuantitativeAnalysisPlanError("dangling Objective")
            bindings={x.expected_variable_id:x for x in item.variable_bindings}
            if not bindings: raise QuantitativeAnalysisPlanError("planned analysis has no reconciled variable")
            for eid,b in bindings.items():
                if eid not in expected or eid not in outcomes: raise QuantitativeAnalysisPlanError("expected variable is unavailable")
                o=outcomes[eid]
                if o.status not in {ReconciliationMatchStatus.EXACT_MATCH,ReconciliationMatchStatus.COMPATIBLE_MATCH} or o.actual_variable_id!=b.actual_variable_id or o.actual_variable_fingerprint!=b.actual_variable_fingerprint: raise QuantitativeAnalysisPlanError("actual variable is not accepted by RB")
                v=actual.get(b.actual_variable_id)
                if v is None or v.fingerprint!=b.actual_variable_fingerprint: raise QuantitativeAnalysisPlanError("VariableDefinition fingerprint mismatch")
                if v.pii_classification is not PiiClassification.NONE: raise QuantitativeAnalysisPlanError("PII-restricted variable cannot be planned")
            if item.obligation not in {"MANDATORY","OPTIONAL"}: raise QuantitativeAnalysisPlanError("unknown analysis obligation")
            spec=item.specification
            if type(spec) not in {AnalysisSpecification,CrossTabAnalysisSpecification,NumericAnalysisSpecification,NpsAnalysisSpecification,CustomIndexAnalysisSpecification}: raise QuantitativeAnalysisPlanError("unsupported analysis specification")
            for rid in item.analytical_requirement_ids:
                if not self._spec_supports_requirement(spec,req[rid].requirement_type): raise QuantitativeAnalysisPlanError("analysis method does not satisfy AnalyticalRequirement")
            ids={spec.variable_id};
            if isinstance(spec,CrossTabAnalysisSpecification): ids.add(spec.column_variable_id)
            if isinstance(spec,CustomIndexAnalysisSpecification): ids.update(x.variable_id for x in spec.terms)
            if getattr(spec,"filter_variable_id",None): ids.add(spec.filter_variable_id)
            if not ids.issubset({b.actual_variable_id for b in item.variable_bindings}): raise QuantitativeAnalysisPlanError("specification variable lacks accepted RB binding")
            if item.execution_support is not AnalysisExecutionSupport.SUPPORTED: raise QuantitativeAnalysisPlanError("unsupported analysis cannot enter execution authority")
            if getattr(spec,"filter_variable_id",None) and item.category_filter is None: raise QuantitativeAnalysisPlanError("filter requires explicit CATEGORY_EQUALS authority")
            if isinstance(spec,NpsAnalysisSpecification) and not any("NPS_SOURCE_0_10" in expected[eid].semantic_hooks for eid in bindings): raise QuantitativeAnalysisPlanError("NPS requires reconciled NPS semantic authority")
            if isinstance(spec,CustomIndexAnalysisSpecification) and (not spec.terms or spec.formula_method!="MEAN_OF_ROW_LINEAR_COMBINATION" or spec.formula_version!="LINEAR_INDEX_V1"): raise QuantitativeAnalysisPlanError("invalid explicit Custom Index formula")
            sfp=fingerprint_analysis_specification(spec,digest_provider=self._digest);spec=replace(spec,fingerprint=sfp)
            if item.category_filter:
                f=item.category_filter;v=actual.get(f.variable_id)
                if v is None or v.fingerprint!=f.variable_fingerprint or not f.semantic_interpretation or canonical_scalar(f.category_code) not in [canonical_scalar(x[0]) for x in v.value_labels]: raise QuantitativeAnalysisPlanError("invalid CATEGORY_EQUALS filter")
                if spec.filter_definition!="CATEGORY_EQUALS" or getattr(spec,"filter_variable_id",None)!=f.variable_id or getattr(spec,"filter_category_value",None)!=f.category_code: raise QuantitativeAnalysisPlanError("filter specification mismatch")
            weighted=item.weighting_policy is AnalysisWeightingPolicy.WEIGHTED_EXACT_WEIGHTSET
            if weighted:
                pair=weight_sets.get(item.planned_analysis_id)
                if pair is None or item.weight_set_binding is None: raise QuantitativeAnalysisPlanError("weighted analysis requires exact WeightSet")
                w,a=pair
                if a.state is not WeightApprovalState.APPROVED or w.dataset_version_id!=dataset.version_id or w.dataset_fingerprint!=dataset.dataset_fingerprint or a.weight_set_id!=w.weight_set_id or a.weight_set_fingerprint!=w.reproducibility_fingerprint or a.dataset_fingerprint!=w.dataset_fingerprint or a.validation_fingerprint!=w.validation_fingerprint or item.weight_set_binding.weight_set_id!=w.weight_set_id or item.weight_set_binding.weight_set_fingerprint!=w.reproducibility_fingerprint or item.weight_set_binding.dataset_version_id!=w.dataset_version_id or item.weight_set_binding.dataset_fingerprint!=w.dataset_fingerprint or item.weight_set_binding.validation_fingerprint!=w.validation_fingerprint or item.weight_set_binding.approval_fingerprint!=a.fingerprint or spec.weighting_status!="WEIGHTED": raise QuantitativeAnalysisPlanError("WeightSet authority is stale")
            elif spec.weighting_status!="UNWEIGHTED" or item.weight_set_binding is not None: raise QuantitativeAnalysisPlanError("unweighted analysis carries weighting authority")
            result.append(replace(item,specification=spec,specification_fingerprint=sfp))
        return tuple(result)
    @staticmethod
    def _spec_supports_requirement(spec,requirement_type):
        kind=requirement_type.strip().upper()
        if kind in {"ONE_WAY","FREQUENCY","TOTAL_DISTRIBUTION","CATEGORICAL_DISTRIBUTION"}: return type(spec) is AnalysisSpecification
        if kind in {"CROSS_TAB","CROSSTAB","SUBGROUP_COMPARISON"}: return isinstance(spec,CrossTabAnalysisSpecification)
        if kind in {"NUMERIC","NUMERIC_SUMMARY","MEAN","MEDIAN"}: return type(spec) is NumericAnalysisSpecification
        if kind in {"NPS","KPI_NPS"}: return isinstance(spec,NpsAnalysisSpecification)
        if kind in {"INDEX","CUSTOM_INDEX"}: return isinstance(spec,CustomIndexAnalysisSpecification)
        return False

    def _validate_comparisons(self,items,analyses,design):
        ids={x.planned_analysis_id for x in analyses};req={x.requirement_id for x in design.analytical_requirements};rqs={x.question_id for x in design.research_questions};out=[]
        for item in items:
            s=item.specification
            if s.method not in {PROPORTION_METHOD,MEAN_METHOD} or s.sidedness!="TWO_SIDED" or s.method_version!="QG_1" or s.filter_definition!="ALL_ROWS" or not Decimal(0)<s.alpha<Decimal(1): raise QuantitativeAnalysisPlanError("unsupported comparison method or inference")
            if not item.precursor_analysis_ids or len(item.precursor_analysis_ids)>2 or any(x not in ids for x in item.precursor_analysis_ids): raise QuantitativeAnalysisPlanError("comparison precursor authority is invalid")
            if {x.role for x in item.result_role_selectors}!={"GROUP_A","GROUP_B"} or len(item.result_role_selectors)!=2 or any(x.precursor_analysis_id not in item.precursor_analysis_ids for x in item.result_role_selectors): raise QuantitativeAnalysisPlanError("comparison result-role authority is invalid")
            if any(x not in req for x in item.analytical_requirement_ids) or any(x not in rqs for x in item.research_question_ids): raise QuantitativeAnalysisPlanError("comparison lineage is invalid")
            if item.obligation not in {"MANDATORY","OPTIONAL"}: raise QuantitativeAnalysisPlanError("unknown comparison obligation")
            if item.objective_ids and any(x not in {o.objective_id for o in design.objectives} for x in item.objective_ids): raise QuantitativeAnalysisPlanError("comparison Objective lineage is invalid")
            if any(next(x for x in analyses if x.planned_analysis_id==pid).weighting_policy is not AnalysisWeightingPolicy.UNWEIGHTED for pid in item.precursor_analysis_ids): raise QuantitativeAnalysisPlanError("weighted significance is unsupported")
            payload={"id":s.comparison_id,"method":s.method,"variable":s.variable_id,"group":s.group_variable_id,"a":canonical_scalar(s.group_a_category),"b":canonical_scalar(s.group_b_category),"outcome":canonical_scalar(s.outcome_category),"alpha":canonical_scalar(s.alpha),"sidedness":s.sidedness,"minimum":s.minimum_group_base,"filter":s.filter_definition,"base":s.base_definition,"version":s.method_version};fp=canonical_digest(payload,digest_provider=self._digest);out.append(replace(item,specification=replace(s,fingerprint=fp),specification_fingerprint=fp))
        return tuple(out)
    def _validate_declarations(self,decls,design):
        valid={x.requirement_id for x in design.analytical_requirements};seen=set()
        for d in decls:
            if d.requirement_id not in valid or d.requirement_id in seen or not " ".join(d.rationale.split()): raise QuantitativeAnalysisPlanError("invalid coverage declaration")
            if d.status is AnalysisPlanCoverageStatus.PARTIALLY_PLANNED and not d.explicit_multi_component: raise QuantitativeAnalysisPlanError("partial coverage requires explicit multi-component authority")
            if d.status not in {AnalysisPlanCoverageStatus.PARTIALLY_PLANNED,AnalysisPlanCoverageStatus.NOT_APPLICABLE,AnalysisPlanCoverageStatus.NOT_ANALYZABLE_UNSUPPORTED_METHOD}: raise QuantitativeAnalysisPlanError("unsupported coverage declaration")
            seen.add(d.requirement_id)
    def _coverage(self,version_id,project_id,content_fp,design,q,r,availability,analyses,decls):
        planned={rid:[] for rid in [x.requirement_id for x in design.analytical_requirements]}
        for a in analyses:
            for rid in a.analytical_requirement_ids: planned[rid].append(a.planned_analysis_id)
        av={x.requirement_id:x.status for x in availability.requirements};dec={x.requirement_id:x for x in decls};entries=[]
        for req in design.analytical_requirements:
            if req.requirement_id in dec: status=dec[req.requirement_id].status;rationale=dec[req.requirement_id].rationale
            elif planned[req.requirement_id]: status=AnalysisPlanCoverageStatus.PLANNED_EXECUTABLE;rationale=None
            elif av.get(req.requirement_id) is DataAvailabilityStatus.TRANSFORMATION_REQUIRED: status=AnalysisPlanCoverageStatus.TRANSFORMATION_REQUIRED;rationale="RB requires authoritative transformation"
            elif av.get(req.requirement_id) in {DataAvailabilityStatus.MISSING_IN_DATA,DataAvailabilityStatus.INCOMPATIBLE_IN_DATA}: status=AnalysisPlanCoverageStatus.BLOCKED_BY_MEASUREMENT;rationale="RB measurement is unavailable"
            else: status=AnalysisPlanCoverageStatus.NOT_PLANNED;rationale="No explicit supported analysis was planned"
            entries.append(AnalysisRequirementPlanCoverage(req.requirement_id,status,tuple(planned[req.requirement_id]),rationale))
        payload={"contract":"RC_COVERAGE_V1","plan_content":content_fp,"qz":design.fingerprint,"ra":q.fingerprint,"rb":r.fingerprint,"entries":tuple((x.requirement_id,x.status.value,x.planned_analysis_ids,x.rationale) for x in entries)};fp=canonical_digest(payload,digest_provider=self._digest);return QuantitativeAnalysisPlanCoverageManifest(f"rc-coverage-{version_id}",project_id,version_id,content_fp,design.fingerprint,q.fingerprint,r.fingerprint,tuple(entries),fp)
    def _content(self,plan_id,project_id,d,q,s,r,dataset,codebook,a,c,declarations,assumptions,limitations):
        return {"contract":"RC_CONTENT_V1","plan":plan_id,"project":project_id,"methodology":"QUANTITATIVE","qz":(d.version_id,d.fingerprint),"ra":(q.version_id,q.fingerprint,s.fingerprint),"rb":(r.version_id,r.fingerprint),"dataset":(dataset.version_id,dataset.dataset_fingerprint,dataset.data_fingerprint,dataset.schema_fingerprint),"codebook":(codebook.codebook_version_id,codebook.fingerprint),"analyses":tuple(self._analysis_payload(x) for x in a),"comparisons":tuple((x.planned_comparison_id,x.specification_fingerprint,x.precursor_analysis_ids,x.objective_ids,x.research_question_ids,x.analytical_requirement_ids,x.expected_result_family,x.obligation,x.assumptions,x.limitations,tuple((v.role,v.precursor_analysis_id,v.statistic_type,v.variable_id,v.group_variable_id,canonical_scalar(v.outcome_category),canonical_scalar(v.group_category),v.filter_definition) for v in x.result_role_selectors)) for x in c),"declarations":tuple((x.requirement_id,x.status.value,x.rationale,x.explicit_multi_component) for x in declarations),"assumptions":assumptions,"limitations":limitations,"version":FINGERPRINT_METHOD_VERSION}
    def _analysis_payload(self,x):
        weight=None if x.weight_set_binding is None else (x.weight_set_binding.weight_set_id,x.weight_set_binding.weight_set_fingerprint,x.weight_set_binding.dataset_version_id,x.weight_set_binding.dataset_fingerprint,x.weight_set_binding.validation_fingerprint,x.weight_set_binding.approval_fingerprint,x.weight_set_binding.effective_sample_size,x.weight_set_binding.limitations)
        category_filter=None if x.category_filter is None else (x.category_filter.variable_id,x.category_filter.variable_fingerprint,canonical_scalar(x.category_filter.category_code),x.category_filter.semantic_interpretation)
        return (x.planned_analysis_id,x.specification_fingerprint,x.objective_ids,x.research_question_ids,x.analytical_requirement_ids,tuple((b.expected_variable_id,b.actual_variable_id,b.actual_variable_fingerprint) for b in x.variable_bindings),x.expected_result_family,x.obligation,x.weighting_policy.value,weight,category_filter,x.assumptions,x.limitations,x.execution_support.value)
    def _require_current(self,value,project_id,run_id,dataset,codebook,weights):
        d,q,s,r,_=self._authority(project_id,run_id,dataset,codebook)
        if (value.research_design_version_id,value.research_design_fingerprint,value.questionnaire_version_id,value.questionnaire_fingerprint,value.expected_measurement_schema_fingerprint,value.reconciliation_version_id,value.reconciliation_fingerprint,value.dataset_version_id,value.dataset_fingerprint,value.data_fingerprint,value.schema_fingerprint,value.codebook_version_id,value.codebook_fingerprint)!=(d.version_id,d.fingerprint,q.version_id,q.fingerprint,s.fingerprint,r.version_id,r.fingerprint,dataset.version_id,dataset.dataset_fingerprint,dataset.data_fingerprint,dataset.schema_fingerprint,codebook.codebook_version_id,codebook.fingerprint): raise QuantitativeAnalysisPlanError("Analysis Plan upstream authority is stale")
        for a in value.planned_analyses:
            if a.weighting_policy is AnalysisWeightingPolicy.WEIGHTED_EXACT_WEIGHTSET:
                pair=weights.get(a.planned_analysis_id)
                if pair is None or pair[0].reproducibility_fingerprint!=a.weight_set_binding.weight_set_fingerprint or pair[1].state is not WeightApprovalState.APPROVED: raise QuantitativeAnalysisPlanError("Analysis Plan WeightSet is stale")
    def _transition(self,vid,project_id,run_id,new,actor,time,status,approval=None):
        old=self._require(vid,project_id);value=replace(old,version_id=new,version_sequence=old.version_sequence+1,parent_version_id=old.version_id,lifecycle_status=status,approval_reference=approval,created_at=time,created_by=actor);cov=self._repository.get_coverage(old.coverage_manifest_id,project_id=project_id);cov=replace(cov,manifest_id=f"rc-coverage-{new}",plan_version_id=new);value=replace(value,coverage_manifest_id=cov.manifest_id,coverage_manifest_fingerprint=cov.fingerprint);self._repository.save_plan(value,run_id=run_id);self._repository.save_coverage(cov,run_id=run_id);return value
    def _require(self,vid,project):
        value=self._repository.get_plan(vid,project_id=project)
        if value is None or value.project_id!=project or value.methodology!="QUANTITATIVE": raise QuantitativeAnalysisPlanError("Quantitative Analysis Plan unavailable for project")
        return value
    def _weight_fps(self,p): return tuple(sorted(x.weight_set_binding.weight_set_fingerprint for x in p.planned_analyses if x.weight_set_binding))

from __future__ import annotations
from dataclasses import replace
from typing import Callable, Mapping

from application.quantitative.comparison_statistics import ComparisonStatisticsService, MEAN_METHOD, PROPORTION_METHOD
from application.quantitative.cross_tab_statistics import CrossTabStatisticsService
from application.quantitative.fingerprints import canonical_digest, canonical_scalar, fingerprint_analysis_specification
from application.quantitative.kpi_statistics import KpiStatisticsService
from application.quantitative.numeric_statistics import NumericStatisticsService
from application.quantitative.one_way_statistics import OneWayStatisticsService
from application.quantitative.state_persistence import QuantitativeStateService, authority_fingerprint
from application.quantitative.weighted_one_way_statistics import WeightedOneWayStatisticsService
from application.quantitative.weighting import build_analytical_view
from domain.quantitative.analysis import AnalysisSpecification, AnalyticalComparisonResult, ComparisonSpecification, CrossTabAnalysisSpecification, CustomIndexAnalysisSpecification, NpsAnalysisSpecification, NumericAnalysisSpecification, StatisticalResult, StatisticalTable
from domain.quantitative.analysis_execution import *
from domain.quantitative.analysis_plan import AnalysisExecutionProjection, AnalysisWeightingPolicy, ComparisonResultRoleSelector, PlannedAnalysis, PlannedComparison
from domain.quantitative.dataset import CodebookVersion, DatasetVersion
from domain.quantitative.quality import DatasetQualityAssessment, DatasetQualityState
from domain.quantitative.weighting import WeightApprovalState, WeightSet, WeightSetApproval, WeightingMode

class QuantitativeAnalysisExecutionError(RuntimeError): pass
class MandatoryAnalysisExecutionError(QuantitativeAnalysisExecutionError): pass

class QuantitativeAnalysisExecutionService:
    def __init__(self,*,repository,state_service:QuantitativeStateService,storage,digest_provider):
        self.repository=repository;self.state=state_service;self.storage=storage;self.digest=digest_provider
        self.one_way=OneWayStatisticsService(storage=storage,digest_provider=digest_provider)
        self.weighted_one_way=WeightedOneWayStatisticsService(storage=storage,digest_provider=digest_provider)
        self.cross_tab=CrossTabStatisticsService(storage=storage,digest_provider=digest_provider)
        self.numeric=NumericStatisticsService(storage=storage,digest_provider=digest_provider)
        self.kpi=KpiStatisticsService(storage=storage,digest_provider=digest_provider)
        self.comparisons=ComparisonStatisticsService(storage=storage,digest_provider=digest_provider)

    def execute(self,*,project_id,run_id,projection:AnalysisExecutionProjection,dataset:DatasetVersion,codebook:CodebookVersion,quality:DatasetQualityAssessment,qc_approval_id,qc_approval_fingerprint,weight_authorities:Mapping[str,tuple[WeightSet,WeightSetApproval]]=None,progress_callback:Callable[[str],None]|None=None,optional_skip_ids=()):
        weights=dict(weight_authorities or {})
        try:
            self._preflight(project_id,run_id,projection,dataset,codebook,quality,qc_approval_id,qc_approval_fingerprint,weights)
        except Exception as exc:
            blocked=self._manifest(project_id,run_id,projection,dataset,codebook,quality,qc_approval_id or "",qc_approval_fingerprint or "",(),(),None,0,AnalysisExecutionManifestStatus.BLOCKED,limitations=(type(exc).__name__,))
            self.repository.save_manifest(blocked)
            raise
        outcomes=[];comparisons=[];parent=None;sequence=0;failed_mandatory=False;optional_failed=False;skip=set(optional_skip_ids)
        for planned in projection.planned_analyses:
            if planned.planned_analysis_id in skip:
                if planned.obligation!="OPTIONAL": raise QuantitativeAnalysisExecutionError("mandatory analysis cannot be skipped")
                outcome=self._failure_analysis(project_id,run_id,projection,dataset,quality,planned,AnalysisItemExecutionStatus.SKIPPED_OPTIONAL,"OPTIONAL_POLICY")
                outcome=self.repository.save_analysis_outcome(outcome)
            else:
                try: outcome=self._analysis(project_id,run_id,projection,dataset,codebook,quality,planned,weights.get(planned.planned_analysis_id))
                except Exception as exc:
                    outcome=self.repository.save_analysis_outcome(self._failure_analysis(project_id,run_id,projection,dataset,quality,planned,AnalysisItemExecutionStatus.FAILED_EXECUTION,f"{type(exc).__name__}:{str(exc)[:160]}"))
                    if planned.obligation=="MANDATORY": failed_mandatory=True
                    else: optional_failed=True
            outcomes.append(outcome);sequence+=1;parent=self._progress(project_id,run_id,projection,dataset,codebook,quality,qc_approval_id,qc_approval_fingerprint,outcomes,comparisons,parent,sequence,progress_callback)

        by_id={x.planned_analysis_id:x for x in outcomes}
        for planned in projection.planned_comparisons:
            if failed_mandatory or any(by_id.get(x) is None or by_id[x].status is not AnalysisItemExecutionStatus.EXECUTED_WITH_RESULTS for x in planned.precursor_analysis_ids):
                outcome=self._failure_comparison(project_id,run_id,projection,dataset,quality,planned,AnalysisItemExecutionStatus.BLOCKED_PRECURSOR,"PRECURSOR_UNAVAILABLE")
            else:
                try: outcome=self._comparison(project_id,run_id,projection,dataset,codebook,quality,planned,by_id)
                except Exception as exc: outcome=self._failure_comparison(project_id,run_id,projection,dataset,quality,planned,AnalysisItemExecutionStatus.BLOCKED_PRECURSOR,f"{type(exc).__name__}:{str(exc)[:160]}")
            outcome=self.repository.save_comparison_outcome(outcome);comparisons.append(outcome);sequence+=1;parent=self._progress(project_id,run_id,projection,dataset,codebook,quality,qc_approval_id,qc_approval_fingerprint,outcomes,comparisons,parent,sequence,progress_callback)
            if outcome.status is not AnalysisItemExecutionStatus.EXECUTED_WITH_RESULTS:
                if planned.obligation=="MANDATORY": failed_mandatory=True
                else: optional_failed=True
        authorized={x.planned_analysis_id for x in projection.planned_analyses};terminal={x.planned_analysis_id for x in outcomes}
        if authorized!=terminal: raise QuantitativeAnalysisExecutionError("authorized and executed PlannedAnalysis sets differ")
        status=AnalysisExecutionManifestStatus.FAILED if failed_mandatory else AnalysisExecutionManifestStatus.COMPLETED_WITH_OPTIONAL_FAILURES if optional_failed else AnalysisExecutionManifestStatus.COMPLETED
        manifest=self._manifest(project_id,run_id,projection,dataset,codebook,quality,qc_approval_id,qc_approval_fingerprint,outcomes,comparisons,parent,sequence+1,status)
        manifest=self.repository.save_manifest(manifest)
        if failed_mandatory:
            failures=tuple(x.failure_category for x in outcomes)+tuple(x.failure_category for x in comparisons)
            first_failure=next((x for x in failures if x), "UNKNOWN")
            raise MandatoryAnalysisExecutionError(f"{manifest.manifest_id}:{first_failure}")
        return manifest

    def record_dataset_only(self,*,project_id,run_id,dataset,codebook,quality,qc_approval_id,qc_approval_fingerprint,legacy_manifest_record_id):
        base=canonical_digest({"run":run_id,"mode":"DATASET_ONLY_EXPLORATORY_EXECUTION","dataset":dataset.dataset_fingerprint,"codebook":codebook.fingerprint,"qc":quality.fingerprint,"legacy":legacy_manifest_record_id,"method":EXECUTION_METHOD_VERSION},digest_provider=self.digest)
        coverage=self.repository.save_coverage(AnalysisExecutionCoverageManifest(f"rd-coverage-{base}",project_id,run_id,f"rd-manifest-{base}",None,(),canonical_digest({"mode":"DATASET_ONLY_EXPLORATORY_EXECUTION","legacy":legacy_manifest_record_id},digest_provider=self.digest)))
        payload={"mode":"DATASET_ONLY_EXPLORATORY_EXECUTION","dataset":dataset.dataset_fingerprint,"codebook":codebook.fingerprint,"qc":quality.fingerprint,"approval":qc_approval_fingerprint,"legacy":legacy_manifest_record_id,"coverage":coverage.fingerprint}
        manifest=QuantitativeAnalysisExecutionManifest(f"rd-manifest-{base}",project_id,run_id,QuantitativeAnalysisExecutionMode.DATASET_ONLY_EXPLORATORY_EXECUTION,EXECUTION_METHOD_VERSION,None,None,None,dataset.version_id,dataset.dataset_fingerprint,dataset.data_fingerprint,dataset.schema_fingerprint,codebook.codebook_version_id,codebook.fingerprint,quality.fingerprint,qc_approval_id,qc_approval_fingerprint,(),(),coverage.coverage_id,coverage.fingerprint,AnalysisExecutionManifestStatus.COMPLETED,None,1,("No RC/QZ/RA/RB design lineage is asserted.",),canonical_digest(payload,digest_provider=self.digest))
        return self.repository.save_manifest(manifest)

    def lineage_projection(self,manifest,*,project_id):
        if manifest.status not in {AnalysisExecutionManifestStatus.COMPLETED,AnalysisExecutionManifestStatus.COMPLETED_WITH_OPTIONAL_FAILURES}: raise QuantitativeAnalysisExecutionError("execution manifest is incomplete")
        entries=[]
        for oid in manifest.analysis_outcome_ids:
            item=self.repository.get_analysis_outcome(oid,project_id=project_id)
            results=tuple((x.authority_id,x.authority_fingerprint) for x in item.artifacts if x.artifact_type=="STATISTICAL_RESULT")
            entries.append(QuantitativeExecutionLineageEntry(item.planned_analysis_id,item.specification_id,item.specification_fingerprint,item.objective_ids,item.research_question_ids,item.analytical_requirement_ids,results,item.status))
        return QuantitativeExecutionLineageProjection(manifest.manifest_id,manifest.fingerprint,manifest.coverage_manifest_id,tuple(entries),manifest.status in {AnalysisExecutionManifestStatus.COMPLETED,AnalysisExecutionManifestStatus.COMPLETED_WITH_OPTIONAL_FAILURES})

    def _preflight(self,project_id,run_id,p,d,c,q,qc_id,qc_fp,weights):
        if d.project_id!=project_id or d.run_id!=run_id: raise QuantitativeAnalysisExecutionError("Dataset project/run authority mismatch")
        if not p.plan_fingerprint or q.state is not DatasetQualityState.QC_APPROVED or not q.current or q.dataset_version_id!=d.version_id or q.dataset_fingerprint!=d.dataset_fingerprint or not q.approval_fingerprint or q.fingerprint!=p.quality_assessment_fingerprint or not qc_id or qc_fp!=q.approval_fingerprint: raise QuantitativeAnalysisExecutionError("stale QC or Plan execution authority")
        if c.fingerprint!=d.codebook_fingerprint or p.plan_fingerprint=="": raise QuantitativeAnalysisExecutionError("stale Dataset/Codebook authority")
        if p.weighting_mode not in {"WEIGHTED", "UNWEIGHTED"} or not p.weighting_authority_fingerprint:
            raise QuantitativeAnalysisExecutionError("explicit study weighting authority is required")
        if p.weighting_mode == "UNWEIGHTED" and weights:
            raise QuantitativeAnalysisExecutionError("unweighted execution carries WeightSet authority")
        actual={x.variable_id:x for x in c.variables}
        for item in p.planned_analyses:
            if item.obligation not in {"MANDATORY","OPTIONAL"}: raise QuantitativeAnalysisExecutionError("unknown analysis obligation")
            if fingerprint_analysis_specification(item.specification,digest_provider=self.digest)!=item.specification_fingerprint: raise QuantitativeAnalysisExecutionError("altered specification fingerprint")
            for b in item.variable_bindings:
                if b.actual_variable_id not in actual or actual[b.actual_variable_id].fingerprint!=b.actual_variable_fingerprint: raise QuantitativeAnalysisExecutionError("stale VariableDefinition authority")
            if item.weighting_policy is AnalysisWeightingPolicy.WEIGHTED_EXACT_WEIGHTSET:
                pair=weights.get(item.planned_analysis_id);binding=item.weight_set_binding
                if not pair or binding is None: raise QuantitativeAnalysisExecutionError("bound WeightSet unavailable")
                w,a=pair
                if a.state is not WeightApprovalState.APPROVED or w.weight_set_id!=binding.weight_set_id or w.reproducibility_fingerprint!=binding.weight_set_fingerprint or w.dataset_version_id!=d.version_id or w.dataset_fingerprint!=d.dataset_fingerprint or w.validation_fingerprint!=binding.validation_fingerprint or a.fingerprint!=binding.approval_fingerprint: raise QuantitativeAnalysisExecutionError("stale WeightSet authority")
            elif item.weight_set_binding is not None: raise QuantitativeAnalysisExecutionError("unweighted analysis carries WeightSet")
        for item in p.planned_comparisons:
            if item.obligation not in {"MANDATORY","OPTIONAL"}: raise QuantitativeAnalysisExecutionError("unknown comparison obligation")
            if item.specification.method not in {PROPORTION_METHOD,MEAN_METHOD}: raise QuantitativeAnalysisExecutionError("unsupported comparison method")
            s=item.specification
            payload={"id":s.comparison_id,"method":s.method,"variable":s.variable_id,"group":s.group_variable_id,"a":canonical_scalar(s.group_a_category),"b":canonical_scalar(s.group_b_category),"outcome":canonical_scalar(s.outcome_category),"alpha":canonical_scalar(s.alpha),"sidedness":s.sidedness,"minimum":s.minimum_group_base,"filter":s.filter_definition,"base":s.base_definition,"version":s.method_version}
            if canonical_digest(payload,digest_provider=self.digest)!=item.specification_fingerprint or s.fingerprint!=item.specification_fingerprint: raise QuantitativeAnalysisExecutionError("altered comparison specification fingerprint")
            if len(item.result_role_selectors)!=2 or {x.role for x in item.result_role_selectors}!={"GROUP_A","GROUP_B"}: raise QuantitativeAnalysisExecutionError("comparison selectors are incomplete")
            precursors={x.planned_analysis_id:x for x in p.planned_analyses}
            if any(x not in precursors for x in item.precursor_analysis_ids): raise QuantitativeAnalysisExecutionError("comparison precursor is unavailable")
            if any(precursors[x].weighting_policy is not AnalysisWeightingPolicy.UNWEIGHTED for x in item.precursor_analysis_ids): raise QuantitativeAnalysisExecutionError("weighted comparison is unsupported")

    def _identity(self,project,run,p,d,q,item_id,spec_fp,variables,weight=None):
        return canonical_digest({"contract":"RD_EXECUTION_ID_V1","project":project,"run":run,"plan":p.plan_fingerprint,"item":item_id,"spec":spec_fp,"dataset":d.dataset_fingerprint,"codebook":d.codebook_fingerprint,"qc":q.fingerprint,"variables":variables,"weight":weight,"method":EXECUTION_METHOD_VERSION},digest_provider=self.digest)

    def _analysis(self,project,run,p,d,c,q,item,weight_pair):
        variables=tuple(sorted((x.actual_variable_id,x.actual_variable_fingerprint) for x in item.variable_bindings));weight_fp=weight_pair[0].reproducibility_fingerprint if weight_pair else None;identity=self._identity(project,run,p,d,q,item.planned_analysis_id,item.specification_fingerprint,variables,weight_fp);oid=f"rd-analysis-{identity}"
        existing=self.repository.get_analysis_outcome(oid,project_id=project)
        if existing is not None:self._verify_artifacts(existing.artifacts,project);return existing
        spec=item.specification;weight,approval=weight_pair if weight_pair else (None,None);artifacts=[]
        if type(spec) is AnalysisSpecification:
            if spec.weighting_status=="WEIGHTED": results=self.weighted_one_way.compute(dataset=d,codebook=c,specification=spec,view=self._view(d,c,q,spec,weight,approval),weight_set=weight)
            else: results=self.one_way.compute(dataset=d,codebook=c,specification=spec)
            table=None
        elif isinstance(spec,CrossTabAnalysisSpecification): table,results=self.cross_tab.compute(dataset=d,codebook=c,specification=spec,view=self._view(d,c,q,spec,weight,approval),weight_set=weight)
        elif isinstance(spec,NpsAnalysisSpecification): results=self.kpi.compute_nps(dataset=d,codebook=c,specification=spec,view=self._view(d,c,q,spec,weight,approval),weight_set=weight);table=None
        elif isinstance(spec,CustomIndexAnalysisSpecification): results=self.kpi.compute_custom_index(dataset=d,codebook=c,specification=spec,view=self._view(d,c,q,spec,weight,approval),weight_set=weight);table=None
        elif type(spec) is NumericAnalysisSpecification: results=self.numeric.compute(dataset=d,codebook=c,specification=spec,view=self._view(d,c,q,spec,weight,approval),weight_set=weight);table=None
        else: raise QuantitativeAnalysisExecutionError("unsupported approved analysis specification")
        for value in results: artifacts.append(self._persist_artifact(value,"STATISTICAL_RESULT",project,run,d.version_id))
        if table is not None: artifacts.append(self._persist_artifact(table,"STATISTICAL_TABLE",project,run,d.version_id))
        self._require_result_family(item.expected_result_family,results,table)
        status=AnalysisItemExecutionStatus.EXECUTED_WITH_RESULTS if results else AnalysisItemExecutionStatus.EXECUTED_NO_VALID_RESULT
        payload={"identity":identity,"status":status.value,"artifacts":tuple((x.record_id,x.authority_fingerprint) for x in artifacts),"lineage":(item.objective_ids,item.research_question_ids,item.analytical_requirement_ids)};fp=canonical_digest(payload,digest_provider=self.digest)
        return self.repository.save_analysis_outcome(PlannedAnalysisExecutionOutcome(oid,project,run,p.plan_version_id,p.plan_fingerprint,item.planned_analysis_id,spec.specification_id,item.specification_fingerprint,item.objective_ids,item.research_question_ids,item.analytical_requirement_ids,variables,weight_fp,status,tuple(artifacts),None,item.limitations,identity,fp))

    def _comparison(self,project,run,p,d,c,q,item,by_id):
        identity=self._identity(project,run,p,d,q,item.planned_comparison_id,item.specification_fingerprint,(),None);oid=f"rd-comparison-{identity}";existing=self.repository.get_comparison_outcome(oid,project_id=project)
        if existing is not None:self._verify_artifacts(existing.artifacts,project);return existing
        selected={}
        for selector in item.result_role_selectors:
            precursor=by_id[selector.precursor_analysis_id]; candidates=[]
            for ref in precursor.artifacts:
                if ref.artifact_type!="STATISTICAL_RESULT":continue
                result=self.state.load(ref.record_id,project_id=project,expected_type=StatisticalResult)
                if self._matches(result,selector):candidates.append(result)
            if len(candidates)!=1: raise QuantitativeAnalysisExecutionError("comparison precursor result is missing or ambiguous")
            selected[selector.role]=candidates[0]
        a,b=selected["GROUP_A"],selected["GROUP_B"];spec=item.specification
        precursor_specs={x.planned_analysis_id:x.specification for x in p.planned_analyses}
        if spec.method==PROPORTION_METHOD:
            source=next(x for x in item.result_role_selectors if x.role=="GROUP_A");view=self._view(d,c,q,precursor_specs[source.precursor_analysis_id],None,None);result=self.comparisons.compare_proportions(dataset=d,codebook=c,specification=spec,group_a_result=a,group_b_result=b,view=view)
        else:
            sa=next(x for x in item.result_role_selectors if x.role=="GROUP_A");sb=next(x for x in item.result_role_selectors if x.role=="GROUP_B");va=self._view(d,c,q,precursor_specs[sa.precursor_analysis_id],None,None);vb=self._view(d,c,q,precursor_specs[sb.precursor_analysis_id],None,None);result=self.comparisons.compare_means(dataset=d,codebook=c,specification=spec,group_a_result=a,group_b_result=b,view_a=va,view_b=vb)
        artifact=self._persist_artifact(result,"COMPARISON_RESULT",project,run,d.version_id);precursor_ids=tuple(by_id[x].outcome_id for x in item.precursor_analysis_ids);payload={"identity":identity,"result":artifact.authority_fingerprint,"precursors":(a.reproducibility_fingerprint,b.reproducibility_fingerprint)};fp=canonical_digest(payload,digest_provider=self.digest)
        return PlannedComparisonExecutionOutcome(oid,project,run,p.plan_version_id,p.plan_fingerprint,item.planned_comparison_id,spec.comparison_id,item.specification_fingerprint,precursor_ids,(a.reproducibility_fingerprint,b.reproducibility_fingerprint),self._comparison_objectives(item,p),item.research_question_ids,item.analytical_requirement_ids,AnalysisItemExecutionStatus.EXECUTED_WITH_RESULTS,(artifact,),None,item.limitations,identity,fp)

    @staticmethod
    def _comparison_objectives(item,p):
        if item.objective_ids: return item.objective_ids
        precursors={x.planned_analysis_id:x for x in p.planned_analyses}
        return tuple(sorted({value for pid in item.precursor_analysis_ids for value in precursors[pid].objective_ids}))

    @staticmethod
    def _require_result_family(expected,results,table):
        aliases={"TOTAL_DISTRIBUTION":{"VALID_N","VALID_PERCENTAGE"},"CROSS_TAB":{"CROSS_TAB_COUNT","CROSS_TAB_ROW_PERCENTAGE","CROSS_TAB_COLUMN_PERCENTAGE"},"NUMERIC_SUMMARY":{"NUMERIC_MEAN","NUMERIC_MEDIAN","NUMERIC_STANDARD_DEVIATION","NUMERIC_VALID_N"},"NPS":{"NPS"},"CUSTOM_INDEX":{"CUSTOM_INDEX"}}
        observed={x.statistic_type for x in results}
        allowed=aliases.get(expected)
        if allowed is None or (results and not observed.intersection(allowed)) or (expected=="CROSS_TAB" and table is None): raise QuantitativeAnalysisExecutionError("unexpected result family")

    @staticmethod
    def _matches(r:StatisticalResult,s:ComparisonResultRoleSelector):
        if r.statistic_type!=s.statistic_type:return False
        if s.statistic_type=="CROSS_TAB_COLUMN_PERCENTAGE": return r.row_variable_id==s.variable_id and r.column_variable_id==s.group_variable_id and r.row_category_value==s.outcome_category and r.column_category_value==s.group_category
        return r.variable_id==s.variable_id and r.filter_definition==s.filter_definition

    def _view(self,d,c,q,spec,weight,approval):
        if isinstance(spec,CrossTabAnalysisSpecification):refs=self.cross_tab.eligible_respondent_refs(dataset=d,codebook=c,specification=spec)
        elif isinstance(spec,(NpsAnalysisSpecification,CustomIndexAnalysisSpecification)):refs=self.kpi.eligible_respondent_refs(dataset=d,codebook=c,specification=spec)
        elif isinstance(spec,NumericAnalysisSpecification):refs=self.numeric.eligible_respondent_refs(dataset=d,codebook=c,specification=spec)
        else:refs=self.storage.get_respondent_lineage(d.version_id)
        mode=WeightingMode.WEIGHTED if spec.weighting_status=="WEIGHTED" else WeightingMode.UNWEIGHTED
        return build_analytical_view(dataset=d,quality=q,specification=spec,mode=mode,respondent_refs=refs,digest_provider=self.digest,weight_set=weight,approval=approval)

    def _persist_artifact(self,value,kind,project,run,dataset_id):
        fp=authority_fingerprint(value);record_id=f"{run}:rd-{kind.lower()}:{fp}"
        try:self.state.persist(value,record_id=record_id,project_id=project,run_id=run,dataset_version_id=dataset_id,accepted=True)
        except ValueError:
            existing=self.state.load(record_id,project_id=project,expected_type=type(value))
            if existing!=value: raise QuantitativeAnalysisExecutionError("conflicting deterministic statistical authority")
        return ExecutionArtifactReference(kind,record_id,getattr(value,"result_id",getattr(value,"table_id",getattr(value,"comparison_result_id",record_id))),fp)
    def _verify_artifacts(self,refs,project):
        types={"STATISTICAL_RESULT":StatisticalResult,"STATISTICAL_TABLE":StatisticalTable,"COMPARISON_RESULT":AnalyticalComparisonResult}
        for ref in refs:
            value=self.state.load(ref.record_id,project_id=project,expected_type=types[ref.artifact_type])
            if authority_fingerprint(value)!=ref.authority_fingerprint: raise QuantitativeAnalysisExecutionError("stale execution artifact")

    def _failure_analysis(self,project,run,p,d,q,item,status,category):
        variables=tuple(sorted((x.actual_variable_id,x.actual_variable_fingerprint) for x in item.variable_bindings));weight=item.weight_set_binding.weight_set_fingerprint if item.weight_set_binding else None;identity=self._identity(project,run,p,d,q,item.planned_analysis_id,item.specification_fingerprint,variables,weight);fp=canonical_digest({"identity":identity,"status":status.value,"category":category},digest_provider=self.digest);return PlannedAnalysisExecutionOutcome(f"rd-analysis-{identity}",project,run,p.plan_version_id,p.plan_fingerprint,item.planned_analysis_id,item.specification.specification_id,item.specification_fingerprint,item.objective_ids,item.research_question_ids,item.analytical_requirement_ids,variables,weight,status,(),category,item.limitations,identity,fp)
    def _failure_comparison(self,project,run,p,d,q,item,status,category):
        identity=self._identity(project,run,p,d,q,item.planned_comparison_id,item.specification_fingerprint,(),None);fp=canonical_digest({"identity":identity,"status":status.value,"category":category},digest_provider=self.digest);return PlannedComparisonExecutionOutcome(f"rd-comparison-{identity}",project,run,p.plan_version_id,p.plan_fingerprint,item.planned_comparison_id,item.specification.comparison_id,item.specification_fingerprint,(),(),self._comparison_objectives(item,p),item.research_question_ids,item.analytical_requirement_ids,status,(),category,item.limitations,identity,fp)

    def _progress(self,project,run,p,d,c,q,qc_id,qc_fp,analyses,comparisons,parent,sequence,callback):
        manifest=self._manifest(project,run,p,d,c,q,qc_id,qc_fp,analyses,comparisons,parent,sequence,AnalysisExecutionManifestStatus.IN_PROGRESS);self.repository.save_manifest(manifest)
        if callback:callback(manifest.manifest_id)
        return manifest.manifest_id
    def _manifest(self,project,run,p,d,c,q,qc_id,qc_fp,analyses,comparisons,parent,sequence,status,limitations=()):
        mid_base=canonical_digest({"run":run,"plan":p.plan_fingerprint,"dataset":d.dataset_fingerprint,"sequence":sequence,"weighting_mode":p.weighting_mode,"weighting_authority":p.weighting_authority_fingerprint,"method":EXECUTION_METHOD_VERSION},digest_provider=self.digest);mid=f"rd-manifest-{mid_base}";entries=tuple(AnalysisExecutionCoverageEntry(x.planned_analysis_id,"ANALYSIS",x.analytical_requirement_ids,x.status,x.outcome_id) for x in analyses)+tuple(AnalysisExecutionCoverageEntry(x.planned_comparison_id,"COMPARISON",x.analytical_requirement_ids,x.status,x.outcome_id) for x in comparisons);cfp=canonical_digest({"manifest":mid,"plan":p.plan_fingerprint,"entries":tuple((x.planned_item_id,x.item_kind,x.status.value,x.outcome_id) for x in entries)},digest_provider=self.digest);coverage=self.repository.save_coverage(AnalysisExecutionCoverageManifest(f"rd-coverage-{mid_base}",project,run,mid,p.plan_fingerprint,entries,cfp));payload={"manifest":mid,"mode":"DESIGN_AWARE_EXECUTION","plan":p.plan_fingerprint,"dataset":d.dataset_fingerprint,"codebook":c.fingerprint,"qc":q.fingerprint,"approval":qc_fp,"weighting_mode":p.weighting_mode,"weighting_authority":p.weighting_authority_fingerprint,"analysis":tuple(x.fingerprint for x in analyses),"comparisons":tuple(x.fingerprint for x in comparisons),"coverage":coverage.fingerprint,"status":status.value,"parent":parent,"sequence":sequence};fp=canonical_digest(payload,digest_provider=self.digest);return QuantitativeAnalysisExecutionManifest(mid,project,run,QuantitativeAnalysisExecutionMode.DESIGN_AWARE_EXECUTION,EXECUTION_METHOD_VERSION,p.plan_id,p.plan_version_id,p.plan_fingerprint,d.version_id,d.dataset_fingerprint,d.data_fingerprint,d.schema_fingerprint,c.codebook_version_id,c.fingerprint,q.fingerprint,qc_id,qc_fp,tuple(x.outcome_id for x in analyses),tuple(x.outcome_id for x in comparisons),coverage.coverage_id,coverage.fingerprint,status,parent,sequence,tuple(limitations),fp,p.weighting_mode,p.weighting_authority_fingerprint)

from dataclasses import replace
import unittest
from unittest.mock import patch

from application.quantitative.analysis_execution import MandatoryAnalysisExecutionError, QuantitativeAnalysisExecutionError, QuantitativeAnalysisExecutionService
from application.quantitative.state_persistence import QuantitativeStateService
from application.quantitative.stage_service_factory import QuantitativeStageServiceFactory
from application.quantitative.workflow import QuantitativeWorkflowError
from application.quantitative.comparison_statistics import PROPORTION_METHOD
from application.quantitative.fingerprints import canonical_digest, canonical_scalar
from domain.quantitative.analysis import ComparisonSpecification
from domain.quantitative.analysis_execution import AnalysisExecutionManifestStatus, AnalysisItemExecutionStatus, QuantitativeAnalysisExecutionMode
from domain.quantitative.analysis_plan import AnalysisWeightingPolicy, ComparisonResultRoleSelector, PlannedComparison
from domain.quantitative.quality import DatasetQualityAssessment, DatasetQualityState
from infrastructure.persistence.quantitative_analysis_execution_repository import QLQuantitativeAnalysisExecutionRepository
from infrastructure.quantitative.storage.in_memory_dataset_storage import InMemoryDatasetStorage
from tests.application.quantitative import test_property_rc_analysis_plan_authority as rc


class PropertyRDAnalysisExecutionTests(unittest.TestCase):
    def setUp(self):
        self.rc=rc.PropertyRCAnalysisPlanAuthorityTests(methodName="runTest"); self.rc.setUp()
        self.rc.approve()
        self.project,self.run=self.rc.project,self.rc.run
        self.dataset,self.codebook=self.rc.dataset,self.rc.codebook
        self.quality=DatasetQualityAssessment(self.dataset.version_id,self.dataset.dataset_fingerprint,"qc-run",DatasetQualityState.QC_APPROVED,"qc-approval-fingerprint",True,"quality-fp")
        self.projection=self.rc.service.execution_projection(project_id=self.project,run_id=self.run,dataset=self.dataset,codebook=self.codebook,quality_assessment=self.quality)
        self.storage=InMemoryDatasetStorage()
        codes=[]
        for variable in self.codebook.variables:
            values=tuple(x[0] for x in variable.value_labels)
            codes.append(values or (1,2))
        rows=[]
        for index in range(10): rows.append(tuple(values[index % len(values)] for values in codes))
        self.storage.put_parsed_rows(self.dataset.version_id,tuple(rows)); self.storage.put_respondent_lineage(self.dataset.version_id,tuple(f"r-{i}" for i in range(10)))
        self.state=QuantitativeStateService(repository=self.rc.backing,digest_provider=self.rc.digest)
        self.repository=QLQuantitativeAnalysisExecutionRepository(self.state)
        self.service=QuantitativeAnalysisExecutionService(repository=self.repository,state_service=self.state,storage=self.storage,digest_provider=self.rc.digest)

    def execute(self,**changes):
        values=dict(project_id=self.project,run_id=self.run,projection=self.projection,dataset=self.dataset,codebook=self.codebook,quality=self.quality,qc_approval_id="qc-approval",qc_approval_fingerprint=self.quality.approval_fingerprint)
        values.update(changes); return self.service.execute(**values)

    def test_approved_rc_plan_executes_exact_set_and_persists_lineage(self):
        manifest=self.execute()
        self.assertEqual(manifest.status,AnalysisExecutionManifestStatus.COMPLETED)
        self.assertEqual(manifest.execution_mode,QuantitativeAnalysisExecutionMode.DESIGN_AWARE_EXECUTION)
        self.assertEqual(len(manifest.analysis_outcome_ids),1)
        outcome=self.repository.get_analysis_outcome(manifest.analysis_outcome_ids[0],project_id=self.project)
        self.assertEqual(outcome.planned_analysis_id,"analysis-brand")
        self.assertEqual(outcome.status,AnalysisItemExecutionStatus.EXECUTED_WITH_RESULTS)
        self.assertTrue(any(x.artifact_type=="STATISTICAL_TABLE" for x in outcome.artifacts))
        projection=self.service.lineage_projection(manifest,project_id=self.project)
        self.assertEqual(projection.entries[0].objective_ids,("objective-brand",))
        self.assertTrue(projection.complete_design_aware_result_set)
        self.assertFalse(hasattr(manifest,"respondent_rows")); self.assertNotIn("r-0",repr(manifest))
        self.assertEqual(self.projection.weighting_mode,"UNWEIGHTED")
        self.assertEqual(manifest.weighting_mode,"UNWEIGHTED")
        self.assertEqual(manifest.weighting_authority_fingerprint,self.projection.weighting_authority_fingerprint)

    def test_global_authority_matrix_blocks_before_statistics(self):
        cases=(
            dict(quality=replace(self.quality,state=DatasetQualityState.QC_PENDING)),
            dict(quality=replace(self.quality,current=False)),
            dict(dataset=replace(self.dataset,dataset_fingerprint="changed")),
            dict(codebook=replace(self.codebook,fingerprint="changed")),
            dict(projection=replace(self.projection,planned_analyses=(replace(self.projection.planned_analyses[0],specification_fingerprint="altered"),))),
            dict(projection=replace(self.projection,planned_analyses=(replace(self.projection.planned_analyses[0],obligation="UNKNOWN"),))),
            dict(project_id="wrong-project"),
        )
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(Exception): self.execute(**case)
        self.assertFalse(any(self.repository.get_manifest(mid,project_id=self.project).analysis_outcome_ids for mid in [x.record_id for x in self.rc.backing.list_for_run(self.run,project_id=self.project) if x.record_type.endswith("QuantitativeAnalysisExecutionManifest")]))

    def test_progress_restart_reuses_identical_authority_without_duplicate_results(self):
        seen=[]
        def interrupt(manifest_id):
            seen.append(manifest_id)
            if len(seen)==1: raise RuntimeError("worker interrupted")
        with self.assertRaisesRegex(RuntimeError,"interrupted"): self.execute(progress_callback=interrupt)
        records_before=tuple(self.rc.backing.list_for_run(self.run,project_id=self.project))
        manifest=self.execute()
        records_after=tuple(self.rc.backing.list_for_run(self.run,project_id=self.project))
        self.assertEqual(len(manifest.analysis_outcome_ids),1)
        before_results={x.record_id for x in records_before if x.record_type.endswith("StatisticalResult")}
        after_results={x.record_id for x in records_after if x.record_type.endswith("StatisticalResult")}
        self.assertEqual(before_results,after_results)
        restarted=QuantitativeAnalysisExecutionService(repository=QLQuantitativeAnalysisExecutionRepository(QuantitativeStateService(repository=self.rc.backing,digest_provider=self.rc.digest)),state_service=QuantitativeStateService(repository=self.rc.backing,digest_provider=self.rc.digest),storage=self.storage,digest_provider=self.rc.digest)
        self.assertEqual(restarted.execute(project_id=self.project,run_id=self.run,projection=self.projection,dataset=self.dataset,codebook=self.codebook,quality=self.quality,qc_approval_id="qc-approval",qc_approval_fingerprint=self.quality.approval_fingerprint).manifest_id,manifest.manifest_id)

    def test_mandatory_optional_failure_and_skip_are_explicit(self):
        item=self.projection.planned_analyses[0]
        bad=replace(item,expected_result_family="UNSUPPORTED")
        mandatory=replace(self.projection,planned_analyses=(bad,))
        with self.assertRaises(MandatoryAnalysisExecutionError): self.execute(projection=mandatory)
        optional=replace(self.projection,plan_fingerprint="optional-plan",planned_analyses=(replace(bad,obligation="OPTIONAL"),))
        manifest=self.execute(projection=optional)
        self.assertEqual(manifest.status,AnalysisExecutionManifestStatus.COMPLETED_WITH_OPTIONAL_FAILURES)
        outcome=self.repository.get_analysis_outcome(manifest.analysis_outcome_ids[0],project_id=self.project)
        self.assertEqual(outcome.status,AnalysisItemExecutionStatus.FAILED_EXECUTION)
        skip_projection=replace(self.projection,plan_fingerprint="skip-plan",planned_analyses=(replace(item,obligation="OPTIONAL"),))
        skipped=self.execute(projection=skip_projection,optional_skip_ids=(item.planned_analysis_id,))
        skipped_outcome=self.repository.get_analysis_outcome(skipped.analysis_outcome_ids[0],project_id=self.project)
        self.assertEqual(skipped_outcome.status,AnalysisItemExecutionStatus.SKIPPED_OPTIONAL)
        with self.assertRaisesRegex(QuantitativeAnalysisExecutionError,"mandatory"): self.execute(optional_skip_ids=(item.planned_analysis_id,))

    def test_dataset_only_manifest_is_explicit_and_has_no_design_lineage(self):
        manifest=self.service.record_dataset_only(project_id=self.project,run_id=self.run,dataset=self.dataset,codebook=self.codebook,quality=self.quality,qc_approval_id="qc-approval",qc_approval_fingerprint=self.quality.approval_fingerprint,legacy_manifest_record_id="legacy-analysis")
        self.assertEqual(manifest.execution_mode,QuantitativeAnalysisExecutionMode.DATASET_ONLY_EXPLORATORY_EXECUTION)
        self.assertIsNone(manifest.plan_id); self.assertIsNone(manifest.plan_fingerprint)
        self.assertEqual(manifest.analysis_outcome_ids,())
        self.assertIn("No RC/QZ/RA/RB",manifest.limitations[0])

    def test_proportion_comparison_uses_two_exact_roles_from_one_cross_tab(self):
        other=rc.PropertyRCAnalysisPlanAuthorityTests(methodName="runTest"); other.setUp()
        row=other.binding.actual_variable_id; column=other.sex_binding.actual_variable_id
        row_values=tuple(x[0] for x in other.codebook.variable_by_id(row).value_labels); column_values=tuple(x[0] for x in other.codebook.variable_by_id(column).value_labels)
        spec=ComparisonSpecification("cmp",PROPORTION_METHOD,row,column,column_values[0],column_values[1],row_values[0])
        selectors=(ComparisonResultRoleSelector("GROUP_A","analysis-brand","CROSS_TAB_COLUMN_PERCENTAGE",row,column,row_values[0],column_values[0],"ALL_ROWS"),ComparisonResultRoleSelector("GROUP_B","analysis-brand","CROSS_TAB_COLUMN_PERCENTAGE",row,column,row_values[0],column_values[1],"ALL_ROWS"))
        comparison=PlannedComparison("planned-cmp",spec,"",("analysis-brand",),("question-preference",),("requirement-preference",),"SIGNIFICANCE",result_role_selectors=selectors,objective_ids=("objective-brand",))
        draft=other.create(planned_comparisons=(comparison,)); approved=other.approve(draft)
        quality=DatasetQualityAssessment(other.dataset.version_id,other.dataset.dataset_fingerprint,"qc",DatasetQualityState.QC_APPROVED,"qc-fp",True,"qfp")
        projection=other.service.execution_projection(project_id=other.project,run_id=other.run,dataset=other.dataset,codebook=other.codebook,quality_assessment=quality)
        storage=InMemoryDatasetStorage(); all_values=tuple(tuple(x[0] for x in variable.value_labels) or (1,2) for variable in other.codebook.variables); rows=tuple(tuple(values[i%len(values)] for values in all_values) for i in range(12)); storage.put_parsed_rows(other.dataset.version_id,rows); storage.put_respondent_lineage(other.dataset.version_id,tuple(f"cmp-{i}" for i in range(12)))
        state=QuantitativeStateService(repository=other.backing,digest_provider=other.digest); repository=QLQuantitativeAnalysisExecutionRepository(state); service=QuantitativeAnalysisExecutionService(repository=repository,state_service=state,storage=storage,digest_provider=other.digest)
        manifest=service.execute(project_id=other.project,run_id=other.run,projection=projection,dataset=other.dataset,codebook=other.codebook,quality=quality,qc_approval_id="qc",qc_approval_fingerprint="qc-fp")
        self.assertEqual(len(manifest.comparison_outcome_ids),1)
        outcome=repository.get_comparison_outcome(manifest.comparison_outcome_ids[0],project_id=other.project)
        self.assertEqual(outcome.status,AnalysisItemExecutionStatus.EXECUTED_WITH_RESULTS)
        self.assertEqual(len(outcome.precursor_result_fingerprints),2)
        self.assertEqual(outcome.objective_ids,("objective-brand",))

    def test_missing_and_ambiguous_comparison_selectors_fail_closed(self):
        item=self.projection.planned_analyses[0]
        spec=ComparisonSpecification("cmp",PROPORTION_METHOD,item.specification.variable_id,item.specification.column_variable_id,"1","2","unknown")
        payload={"id":spec.comparison_id,"method":spec.method,"variable":spec.variable_id,"group":spec.group_variable_id,"a":canonical_scalar(spec.group_a_category),"b":canonical_scalar(spec.group_b_category),"outcome":canonical_scalar(spec.outcome_category),"alpha":canonical_scalar(spec.alpha),"sidedness":spec.sidedness,"minimum":spec.minimum_group_base,"filter":spec.filter_definition,"base":spec.base_definition,"version":spec.method_version}; fp=canonical_digest(payload,digest_provider=self.rc.digest); spec=replace(spec,fingerprint=fp)
        selectors=(ComparisonResultRoleSelector("GROUP_A",item.planned_analysis_id,"CROSS_TAB_COLUMN_PERCENTAGE",item.specification.variable_id,item.specification.column_variable_id,"unknown","1","ALL_ROWS"),ComparisonResultRoleSelector("GROUP_B",item.planned_analysis_id,"CROSS_TAB_COLUMN_PERCENTAGE",item.specification.variable_id,item.specification.column_variable_id,"unknown","2","ALL_ROWS"))
        planned=PlannedComparison("cmp",spec,fp,(item.planned_analysis_id,),item.research_question_ids,item.analytical_requirement_ids,"SIGNIFICANCE",result_role_selectors=selectors,objective_ids=item.objective_ids)
        projection=replace(self.projection,plan_fingerprint="missing-selector-plan",planned_comparisons=(planned,))
        with self.assertRaises(MandatoryAnalysisExecutionError): self.execute(projection=projection)
        incomplete=replace(planned,result_role_selectors=selectors[:1])
        with self.assertRaisesRegex(QuantitativeAnalysisExecutionError,"selectors"): self.execute(projection=replace(projection,plan_fingerprint="incomplete-selector-plan",planned_comparisons=(incomplete,)))
    def test_design_aware_factory_fails_closed_without_rc_and_never_calls_heuristic(self):
        self.state.persist(self.dataset,record_id="rd-factory-dataset",project_id=self.project,run_id=self.run,dataset_version_id=self.dataset.version_id)
        self.state.persist(self.codebook,record_id="rd-factory-codebook",project_id=self.project,run_id=self.run,dataset_version_id=self.dataset.version_id)
        factory=QuantitativeStageServiceFactory(state_service=self.state,digest_provider=self.rc.digest,storage_factory=lambda project,run:self.storage,importers=(),finding_generator=object(),insight_generator=object(),report_generator=object(),generation_mode="offline")
        safe={"dataset_record_id":"rd-factory-dataset","codebook_record_id":"rd-factory-codebook","analysis_execution_mode":"DESIGN_AWARE_EXECUTION"}
        with patch.object(QuantitativeStageServiceFactory,"_build_plan",side_effect=AssertionError("heuristic called")):
            with self.assertRaisesRegex(QuantitativeWorkflowError,"composition"): factory.create(project_id=self.project,run_id=self.run,safe_state=safe)
    def test_wrong_project_and_corrupted_replay_fail_closed(self):
        manifest=self.execute(); outcome_id=manifest.analysis_outcome_ids[0]
        self.assertIsNone(self.repository.get_analysis_outcome(outcome_id,project_id="wrong"))
        record=self.rc.backing._records[outcome_id]
        self.rc.backing._records[outcome_id]=replace(record,authority_fingerprint="corrupt")
        with self.assertRaises(Exception): self.execute()


if __name__=="__main__": unittest.main()

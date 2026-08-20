from __future__ import annotations

import unittest
from dataclasses import replace
from decimal import Decimal

from application.quantitative.dataset_import_service import QuantitativeDatasetImportService, VariableOverride
from application.quantitative.fingerprints import canonical_digest
from application.quantitative.quality_control import assess_dataset_quality, build_questionnaire_snapshot, DataQualityService
from application.quantitative.target_margin_weighting import TargetMarginWeightingService, build_weighting_target_plan
from application.quantitative.weighted_one_way_statistics import WeightedOneWayStatisticsService
from application.quantitative.weighting import approve_weight_set, build_analytical_view, WeightingError
from application.quantitative.vertical_service import QuantitativeVerticalPlan, RealQuantitativeStageService
from application.quantitative.state_persistence import QuantitativeStateService
from application.quantitative.workflow import QuantitativeApprovalService, validate_safe_workflow_state
from domain.quantitative.analysis import AnalysisSpecification
from domain.quantitative.dataset import DatasetFormat, VariableRole, VariableType
from domain.quantitative.weighting import WeightTrimmingPolicy, WeightingMode, WeightingTargetMargin
from infrastructure.quantitative.importers.xlsx_openpyxl_adapter import XlsxOpenpyxlAdapter
from infrastructure.quantitative.storage.in_memory_dataset_storage import InMemoryDatasetStorage
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from infrastructure.persistence.memory.in_memory_quantitative_state_repository import InMemoryQuantitativeStateRepository
from tests.application.quantitative.test_property_qa_byte_to_statistic_provenance import xlsx_bytes


class PropertyQNTests(unittest.TestCase):
    def setUp(self):
        self.digest=Sha256DigestProvider(); self.storage=InMemoryDatasetStorage()
        rows=[
            ["r1","F","Y","N","A"],["r2","F","Y","N","A"],["r3","F","Y","N","A"],
            ["r4","F","M","N","B"],["r5","F","M","S","B"],["r6","F","M","S","B"],
            ["r7","M","Y","N","A"],["r8","M","M","S","B"],
        ]
        imported=QuantitativeDatasetImportService(importers=(XlsxOpenpyxlAdapter(),),storage=self.storage,digest_provider=self.digest).import_bytes(xlsx_bytes(["id","sex","age","region","choice"],rows),filename="survey.xlsx",dataset_format=DatasetFormat.XLSX,dataset_id="qn-data",project_id="p",run_id="r",data_sheet="Data",overrides={"id":VariableOverride(variable_type=VariableType.TECHNICAL_ID,role=VariableRole.TECHNICAL_ID),"sex":VariableOverride(variable_type=VariableType.DEMOGRAPHIC,role=VariableRole.DEMOGRAPHIC),"age":VariableOverride(variable_type=VariableType.DEMOGRAPHIC,role=VariableRole.DEMOGRAPHIC),"region":VariableOverride(variable_type=VariableType.DEMOGRAPHIC,role=VariableRole.DEMOGRAPHIC),"choice":VariableOverride(variable_type=VariableType.CATEGORICAL)})
        self.dataset,self.codebook=imported.dataset_version,imported.codebook
        self.variables={item.name:item for item in self.codebook.variables}
        self.service=TargetMarginWeightingService(storage=self.storage,digest_provider=self.digest)

    def margin(self,name,values): return WeightingTargetMargin(self.variables[name].variable_id,tuple((key,Decimal(value)) for key,value in values))
    def plan(self,*margins,**changes):
        args=dict(plan_id="targets-v1",dataset=self.dataset,margins=tuple(margins),target_source="approved synthetic targets",target_total_tolerance=Decimal("0.000001"),convergence_tolerance=Decimal("0.000001"),maximum_iterations=100,minimum_weight=Decimal("0.1"),maximum_weight=Decimal("10"),trimming_policy=WeightTrimmingPolicy.NONE,digest_provider=self.digest)
        args.update(changes); return build_weighting_target_plan(**args)

    def test_one_margin_converges_and_effective_sample_is_authoritative(self):
        plan=self.plan(self.margin("sex",(("F","0.5"),("M","0.5"))))
        result=self.service.construct(dataset=self.dataset,codebook=self.codebook,plan=plan)
        self.assertTrue(result.convergence_diagnostic.converged)
        self.assertLessEqual(result.convergence_diagnostic.maximum_absolute_margin_error,plan.convergence_tolerance)
        expected=(result.sum_weights**2)/sum(weight**2 for _,weight in result.weight_vector)
        self.assertLess(abs(result.effective_sample_size-expected),Decimal("1e-25"))
        self.assertEqual(result.dataset_version_id,self.dataset.version_id)

    def test_three_margins_are_deterministic_and_changed_target_changes_identity(self):
        margins=(self.margin("sex",(("F","0.5"),("M","0.5"))),self.margin("age",(("Y","0.4"),("M","0.6"))),self.margin("region",(("N","0.55"),("S","0.45"))))
        plan=self.plan(*margins); first=self.service.construct(dataset=self.dataset,codebook=self.codebook,plan=plan); second=self.service.construct(dataset=self.dataset,codebook=self.codebook,plan=plan)
        self.assertEqual(first,second)
        changed=self.plan(margins[0],margins[1],self.margin("region",(("N","0.6"),("S","0.4"))))
        self.assertNotEqual(first.reproducibility_fingerprint,self.service.construct(dataset=self.dataset,codebook=self.codebook,plan=changed).reproducibility_fingerprint)

    def test_invalid_target_total_unknown_category_and_empty_positive_cell_fail_closed(self):
        cases=(self.margin("sex",(("F","0.7"),("M","0.4"))),self.margin("sex",(("F","0.5"),("X","0.5"))))
        for margin in cases:
            with self.assertRaises(WeightingError): self.service.construct(dataset=self.dataset,codebook=self.codebook,plan=self.plan(margin))
        empty=replace(self.margin("sex",(("F","0.5"),("M","0.5"))),category_targets=(("F",Decimal("0.4")),("M",Decimal("0.4")),("X",Decimal("0.2"))))
        with self.assertRaises(WeightingError): self.service.construct(dataset=self.dataset,codebook=replace(self.codebook,variables=tuple(replace(v,value_labels=()) if v.name=="sex" else v for v in self.codebook.variables)),plan=self.plan(empty))

    def test_unknown_or_non_categorical_control_and_stale_dataset_fail_closed(self):
        unknown=WeightingTargetMargin("unknown",(("A",Decimal(1)),))
        with self.assertRaises(WeightingError): self.service.construct(dataset=self.dataset,codebook=self.codebook,plan=self.plan(unknown))
        numeric=replace(self.margin("sex",(("F","0.5"),("M","0.5"))),variable_id=self.variables["id"].variable_id)
        with self.assertRaises(WeightingError): self.service.construct(dataset=self.dataset,codebook=self.codebook,plan=self.plan(numeric))
        stale=replace(self.plan(self.margin("sex",(("F","0.5"),("M","0.5")))),dataset_fingerprint="stale")
        with self.assertRaises(WeightingError): self.service.construct(dataset=self.dataset,codebook=self.codebook,plan=stale)

    def test_missing_control_and_nonconvergence_fail_closed(self):
        original=self.storage.get_parsed_rows(self.dataset.version_id); rows=list(original); rows[0]=tuple(None if i==1 else value for i,value in enumerate(rows[0])); self.storage._rows[self.dataset.version_id]=tuple(rows)
        with self.assertRaisesRegex(WeightingError,"missing"): self.service.construct(dataset=self.dataset,codebook=self.codebook,plan=self.plan(self.margin("sex",(("F","0.5"),("M","0.5")))))
        self.storage._rows[self.dataset.version_id]=original
        hard=self.plan(self.margin("sex",(("F","0.9"),("M","0.1"))),self.margin("region",(("N","0.1"),("S","0.9"))),maximum_iterations=1,convergence_tolerance=Decimal("0.000000000001"),minimum_weight=Decimal("0.0001"),maximum_weight=Decimal("1000"))
        with self.assertRaisesRegex(WeightingError,"did not converge"): self.service.construct(dataset=self.dataset,codebook=self.codebook,plan=hard)

    def test_bounds_fail_or_clip_explicitly_and_report_diagnostics(self):
        margin=self.margin("sex",(("F","0.1"),("M","0.9")))
        with self.assertRaisesRegex(WeightingError,"bounds"): self.service.construct(dataset=self.dataset,codebook=self.codebook,plan=self.plan(margin,maximum_weight=Decimal("2")))
        clipped=self.plan(margin,minimum_weight=Decimal("0.01"),maximum_weight=Decimal("3"),trimming_policy=WeightTrimmingPolicy.CLIP,convergence_tolerance=Decimal("0.2"))
        result=self.service.construct(dataset=self.dataset,codebook=self.codebook,plan=clipped)
        self.assertTrue(result.convergence_diagnostic.trimming_applied)
        self.assertTrue(all(clipped.minimum_weight<=weight<=clipped.maximum_weight for _,weight in result.weight_vector))

    def test_existing_approval_and_analytical_view_accept_constructed_weightset(self):
        weights=self.service.construct(dataset=self.dataset,codebook=self.codebook,plan=self.plan(self.margin("sex",(("F","0.5"),("M","0.5")))))
        approval=approve_weight_set(weight_set=weights,approver_id="analyst",approved_at="2026-08-20",digest_provider=self.digest)
        questionnaire=build_questionnaire_snapshot(snapshot_id="q",version="1",codebook_version_id=self.codebook.codebook_version_id,question_variable_bindings=(),digest_provider=self.digest)
        qc=DataQualityService(storage=self.storage,digest_provider=self.digest).detect(dataset=self.dataset,codebook=self.codebook,questionnaire=questionnaire,detection_run_id="qc")
        quality=assess_dataset_quality(dataset=self.dataset,qc_run=qc,manager_approved=True,approval_fingerprint="qc-approved",digest_provider=self.digest)
        spec=AnalysisSpecification("weighted-choice",self.variables["choice"].variable_id,weighting_status="WEIGHTED")
        refs=self.storage.get_respondent_lineage(self.dataset.version_id)
        view=build_analytical_view(dataset=self.dataset,quality=quality,specification=spec,mode=WeightingMode.WEIGHTED,respondent_refs=refs,digest_provider=self.digest,weight_set=weights,approval=approval)
        results=WeightedOneWayStatisticsService(storage=self.storage,digest_provider=self.digest).compute(dataset=self.dataset,codebook=self.codebook,specification=spec,view=view,weight_set=weights)
        self.assertTrue(results)
        changed_plan=self.plan(self.margin("sex",(("F","0.6"),("M","0.4"))))
        changed=self.service.construct(dataset=self.dataset,codebook=self.codebook,plan=changed_plan)
        self.assertNotEqual(approval.weight_set_fingerprint,changed.reproducibility_fingerprint)

    def test_qm_weightset_stage_constructs_from_targets_with_safe_state_only(self):
        target=self.plan(self.margin("sex",(("F","0.5"),("M","0.5"))))
        repository=InMemoryQuantitativeStateRepository(); state_service=QuantitativeStateService(repository=repository,digest_provider=self.digest)
        dataset_id="r:dataset"; codebook_id="r:codebook"
        state_service.persist(self.dataset,record_id=dataset_id,project_id="p",run_id="r",dataset_version_id=self.dataset.version_id)
        state_service.persist(self.codebook,record_id=codebook_id,project_id="p",run_id="r",dataset_version_id=self.dataset.version_id)
        spec=AnalysisSpecification("placeholder",self.variables["choice"].variable_id)
        plan=QuantitativeVerticalPlan(b"","unused.sav","qn-data",{},build_questionnaire_snapshot(snapshot_id="q2",version="1",codebook_version_id=self.codebook.codebook_version_id,question_variable_bindings=(),digest_provider=self.digest),(),"",spec,None,None,None,weight_mode="CONSTRUCT_FROM_TARGET_MARGINS",weighting_target_plan=target)
        facade=RealQuantitativeStageService(plan=plan,storage=self.storage,digest_provider=self.digest,state_service=state_service,approval_service=QuantitativeApprovalService(state_service,self.digest),finding_service=None,insight_service=None,report_service=None,importers=())
        safe=facade.execute_stage("quant_weightset",project_id="p",run_id="r",safe_state={"dataset_record_id":dataset_id,"codebook_record_id":codebook_id})
        validate_safe_workflow_state(safe)
        constructed=state_service.load(safe["weight_set_record_id"],project_id="p")
        self.assertEqual(constructed.construction_plan_fingerprint,target.fingerprint)


if __name__ == "__main__": unittest.main()

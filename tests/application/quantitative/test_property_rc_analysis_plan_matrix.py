from dataclasses import replace
from decimal import Decimal
import unittest

from application.quantitative.analysis_planning import QuantitativeAnalysisPlanError
from application.quantitative.state_persistence import QuantitativePersistenceError
from domain.quantitative.analysis import AnalysisSpecification, CrossTabAnalysisSpecification, CustomIndexAnalysisSpecification, IndexTerm, NpsAnalysisSpecification, NumericAnalysisSpecification
from domain.quantitative.analysis_plan import AnalysisExecutionSupport, CategoryEqualsFilter
from domain.quantitative.quality import DatasetQualityAssessment, DatasetQualityState
from tests.application.quantitative import test_property_rc_analysis_plan_authority as rc


class PropertyRCContractMatrixTests(rc.PropertyRCAnalysisPlanAuthorityTests):
    def test_supported_analysis_family_matrix_and_substitution(self):
        actual=self.binding.actual_variable_id
        matrix=((AnalysisSpecification("one",actual),"TOTAL_DISTRIBUTION",True),(CrossTabAnalysisSpecification(specification_id="cross",variable_id=actual,column_variable_id=self.sex_binding.actual_variable_id),"CROSS_TAB",True),(NumericAnalysisSpecification("numeric",actual),"NUMERIC_SUMMARY",True),(NpsAnalysisSpecification("nps",actual),"NPS",True),(CustomIndexAnalysisSpecification("index",actual,terms=(IndexTerm(actual,Decimal("1")),)),"CUSTOM_INDEX",True),(AnalysisSpecification("wrong",actual),"CROSS_TAB",False),(NumericAnalysisSpecification("wrong-nps",actual),"NPS",False),(AnalysisSpecification("unknown",actual),"CONJOINT",False))
        for spec,requirement,expected in matrix:
            with self.subTest(requirement=requirement,spec=type(spec).__name__): self.assertEqual(self.service._spec_supports_requirement(spec,requirement),expected)
        with self.assertRaisesRegex(QuantitativeAnalysisPlanError,"does not satisfy"):
            self.create(planned_analyses=(replace(self.analysis,specification=AnalysisSpecification("substitute",actual)),))

    def test_duplicate_missing_lineage_and_unsupported_execution(self):
        with self.assertRaisesRegex(QuantitativeAnalysisPlanError,"duplicate"): self.create(planned_analyses=(self.analysis,self.analysis))
        for changed in (replace(self.analysis,research_question_ids=()),replace(self.analysis,analytical_requirement_ids=())):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(QuantitativeAnalysisPlanError,"lineage"): self.create(version_id="bad-"+str(len(changed.research_question_ids)),planned_analyses=(changed,))
        other=rc.PropertyRCAnalysisPlanAuthorityTests(methodName="runTest"); other.setUp()
        with self.assertRaisesRegex(QuantitativeAnalysisPlanError,"unsupported analysis"):
            other.create(planned_analyses=(replace(other.analysis,execution_support=AnalysisExecutionSupport.UNSUPPORTED),))

    def test_category_equals_filter_contract(self):
        variable=next(x for x in self.codebook.variables if x.variable_id==self.sex_binding.actual_variable_id)
        spec=replace(self.analysis.specification,filter_definition="CATEGORY_EQUALS",filter_variable_id=variable.variable_id,filter_category_value="1")
        authority=CategoryEqualsFilter(variable.variable_id,variable.fingerprint,"1","Group A respondents")
        value=self.create(planned_analyses=(replace(self.analysis,specification=spec,category_filter=authority),))
        self.assertEqual(value.planned_analyses[0].category_filter,authority)
        other=rc.PropertyRCAnalysisPlanAuthorityTests(methodName="runTest"); other.setUp(); implicit=replace(other.analysis.specification,filter_variable_id=other.sex_binding.actual_variable_id,filter_category_value="1")
        with self.assertRaisesRegex(QuantitativeAnalysisPlanError,"explicit CATEGORY_EQUALS"): other.create(planned_analyses=(replace(other.analysis,specification=implicit),))
        third=rc.PropertyRCAnalysisPlanAuthorityTests(methodName="runTest"); third.setUp(); v=next(x for x in third.codebook.variables if x.variable_id==third.sex_binding.actual_variable_id); bad=CategoryEqualsFilter(v.variable_id,v.fingerprint,"999","unknown"); badspec=replace(third.analysis.specification,filter_definition="CATEGORY_EQUALS",filter_variable_id=v.variable_id,filter_category_value="999")
        with self.assertRaisesRegex(QuantitativeAnalysisPlanError,"invalid CATEGORY_EQUALS"): third.create(planned_analyses=(replace(third.analysis,specification=badspec,category_filter=bad),))

    def test_fingerprint_determinism_and_spec_change(self):
        first=self.create(); other=rc.PropertyRCAnalysisPlanAuthorityTests(methodName="runTest"); other.setUp(); same=other.create(); self.assertEqual(first.fingerprint,same.fingerprint)
        third=rc.PropertyRCAnalysisPlanAuthorityTests(methodName="runTest"); third.setUp(); changed_spec=replace(third.analysis.specification,presentation_threshold_percent=Decimal("2")); changed=third.create(planned_analyses=(replace(third.analysis,specification=changed_spec),)); self.assertNotEqual(first.fingerprint,changed.fingerprint)

    def test_qc_execution_staleness_matrix(self):
        self.approve(); cases=(None,DatasetQualityAssessment(self.dataset.version_id,self.dataset.dataset_fingerprint,"qc",DatasetQualityState.QC_PENDING,None,True,"pending"),DatasetQualityAssessment("other",self.dataset.dataset_fingerprint,"qc",DatasetQualityState.QC_APPROVED,"approval",True,"wrong-version"),DatasetQualityAssessment(self.dataset.version_id,"altered","qc",DatasetQualityState.QC_APPROVED,"approval",True,"wrong-fingerprint"),DatasetQualityAssessment(self.dataset.version_id,self.dataset.dataset_fingerprint,"qc",DatasetQualityState.QC_APPROVED,"approval",False,"not-current"))
        for quality in cases:
            with self.subTest(quality=quality):
                with self.assertRaisesRegex(QuantitativeAnalysisPlanError,"QC authority"): self.service.execution_projection(project_id=self.project,run_id=self.run,dataset=self.dataset,codebook=self.codebook,quality_assessment=quality)

    def test_wrong_project_corruption_and_payload_safety(self):
        approved=self.approve(); self.assertFalse(hasattr(approved,"respondent_rows")); self.assertFalse(hasattr(self.service.approved_projection(project_id=self.project,run_id=self.run,dataset=self.dataset,codebook=self.codebook),"respondent_values"))
        with self.assertRaises(QuantitativeAnalysisPlanError): self.service.resolve_current_approved(project_id="wrong",run_id=self.run,dataset=self.dataset,codebook=self.codebook)
        self.backing._records[approved.version_id]=replace(self.backing._records[approved.version_id],authority_fingerprint="corrupt")
        with self.assertRaises((QuantitativePersistenceError,QuantitativeAnalysisPlanError)): self.service.resolve_current_approved(project_id=self.project,run_id=self.run,dataset=self.dataset,codebook=self.codebook)


if __name__=="__main__": unittest.main()

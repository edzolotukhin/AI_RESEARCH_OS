from dataclasses import replace
from decimal import Decimal
import unittest

from application.quantitative.analysis_planning import QuantitativeAnalysisPlanError, QuantitativeAnalysisPlanService
from application.quantitative.state_persistence import QuantitativePersistenceError, QuantitativeStateService
from domain.quantitative.analysis import AnalysisSpecification, ComparisonSpecification, CrossTabAnalysisSpecification, CustomIndexAnalysisSpecification, IndexTerm, NpsAnalysisSpecification, NumericAnalysisSpecification
from domain.quantitative.analysis_plan import (
    AnalysisExecutionSupport, AnalysisPlanCoverageDeclaration, AnalysisPlanCoverageStatus, CategoryEqualsFilter,
    AnalysisPlanLifecycle, AnalysisWeightingPolicy, PlanVariableBinding, PlannedAnalysis,
    PlannedComparison,
)
from domain.quantitative.dataset import PiiClassification
from domain.quantitative.quality import DatasetQualityAssessment, DatasetQualityState
from infrastructure.persistence.quantitative_analysis_plan_repository import QLQuantitativeAnalysisPlanRepository
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.application.quantitative.test_property_rb_measurement_reconciliation import PropertyRBMeasurementReconciliationTests


class PropertyRCAnalysisPlanAuthorityTests(unittest.TestCase):
    def setUp(self):
        rb=PropertyRBMeasurementReconciliationTests(methodName="runTest"); rb.setUp()
        self.rb=rb; self.reconciliation=rb.create(); self.project,self.run=rb.project,rb.run
        self.dataset,self.codebook=rb.dataset,rb.codebook; self.digest=Sha256DigestProvider(); self.backing=rb.backing
        self.repository=QLQuantitativeAnalysisPlanRepository(QuantitativeStateService(repository=self.backing,digest_provider=self.digest))
        questionnaire_service=rb.service._questionnaires
        self.service=QuantitativeAnalysisPlanService(repository=self.repository,research_design_service=questionnaire_service._designs,questionnaire_service=questionnaire_service,reconciliation_service=rb.service,digest_provider=self.digest)
        expected=next(x for x in rb.schema.variables if x.expected_variable_id=="ev-brand")
        actual=next(x for x in self.codebook.variables if x.variable_id=="actual-ev-brand")
        self.binding=PlanVariableBinding(expected.expected_variable_id,actual.variable_id,actual.fingerprint)
        sex_expected=next(x for x in rb.schema.variables if x.expected_variable_id=="ev-sex")
        sex_actual=next(x for x in self.codebook.variables if x.variable_id=="actual-ev-sex")
        self.sex_binding=PlanVariableBinding(sex_expected.expected_variable_id,sex_actual.variable_id,sex_actual.fingerprint)
        spec=CrossTabAnalysisSpecification(specification_id="spec-brand",variable_id=actual.variable_id,column_variable_id=sex_actual.variable_id)
        self.analysis=PlannedAnalysis("analysis-brand",spec,"",("objective-brand",),("question-preference",),("requirement-preference",),(self.binding,self.sex_binding),"CROSS_TAB","MANDATORY",AnalysisWeightingPolicy.UNWEIGHTED,None,None,(),(),AnalysisExecutionSupport.SUPPORTED)

    def create(self,**overrides):
        values=dict(plan_id="plan",version_id="plan-v1",project_id=self.project,run_id=self.run,dataset=self.dataset,codebook=self.codebook,planned_analyses=(self.analysis,),created_at="now",created_by="researcher")
        values.update(overrides); return self.service.create_draft(**values)

    def approve(self,draft=None):
        draft=draft or self.create(); review=self.service.submit_for_review(draft.version_id,project_id=self.project,run_id=self.run,new_version_id="plan-review",actor_id="researcher",changed_at="later")
        return self.service.approve(review.version_id,project_id=self.project,run_id=self.run,new_version_id="plan-approved",approval_id="plan-approval",expected_fingerprint=review.fingerprint,actor_id="owner",decided_at="latest",rationale="Methodologically reviewed",dataset=self.dataset,codebook=self.codebook)

    def test_draft_is_deterministic_traceable_and_immutable_revision(self):
        draft=self.create(); self.assertEqual(draft.lifecycle_status,AnalysisPlanLifecycle.DRAFT)
        self.assertEqual(draft.research_design_fingerprint,self.rb.questionnaire.research_design_fingerprint)
        self.assertEqual(draft.reconciliation_fingerprint,self.reconciliation.fingerprint)
        revised=self.service.revise(draft.version_id,project_id=self.project,run_id=self.run,new_version_id="plan-v2",dataset=self.dataset,codebook=self.codebook,created_at="later",created_by="editor",limitations=("Revised limitation",))
        self.assertEqual(revised.parent_version_id,draft.version_id); self.assertNotEqual(revised.fingerprint,draft.fingerprint)
        self.assertEqual(self.repository.get_plan(draft.version_id,project_id=self.project),draft)

    def test_approval_is_required_fingerprint_bound_and_projections_are_bounded(self):
        draft=self.create()
        with self.assertRaises(QuantitativeAnalysisPlanError): self.service.approved_projection(project_id=self.project,run_id=self.run,dataset=self.dataset,codebook=self.codebook)
        review=self.service.submit_for_review(draft.version_id,project_id=self.project,run_id=self.run,new_version_id="plan-review",actor_id="r",changed_at="later")
        with self.assertRaisesRegex(QuantitativeAnalysisPlanError,"stale"):
            self.service.approve(review.version_id,project_id=self.project,run_id=self.run,new_version_id="bad",approval_id="bad",expected_fingerprint="altered",actor_id="o",decided_at="x",rationale="reviewed",dataset=self.dataset,codebook=self.codebook)
        approved=self.service.approve(review.version_id,project_id=self.project,run_id=self.run,new_version_id="plan-approved",approval_id="approval",expected_fingerprint=review.fingerprint,actor_id="o",decided_at="x",rationale="reviewed",dataset=self.dataset,codebook=self.codebook)
        projection=self.service.approved_projection(project_id=self.project,run_id=self.run,dataset=self.dataset,codebook=self.codebook)
        self.assertEqual(projection.version_id,approved.version_id); self.assertFalse(hasattr(projection,"respondent_rows"))
        with self.assertRaisesRegex(QuantitativeAnalysisPlanError,"QC"):
            self.service.execution_projection(project_id=self.project,run_id=self.run,dataset=self.dataset,codebook=self.codebook)
        execution=self.service.execution_projection(project_id=self.project,run_id=self.run,dataset=self.dataset,codebook=self.codebook,quality_assessment=DatasetQualityAssessment(self.dataset.version_id,self.dataset.dataset_fingerprint,"qc-run",DatasetQualityState.QC_APPROVED,"qc-approval",True,"quality-fp"))
        self.assertEqual(execution.specifications[0].specification_id,"spec-brand")

    def test_stale_dataset_codebook_and_actual_fingerprint_fail_closed(self):
        self.approve()
        for dataset,codebook in ((replace(self.dataset,version_id="new"),self.codebook),(self.dataset,replace(self.codebook,fingerprint="changed"))):
            with self.assertRaises(Exception): self.service.resolve_current_approved(project_id=self.project,run_id=self.run,dataset=dataset,codebook=codebook)
        bad=replace(self.analysis,variable_bindings=(replace(self.binding,actual_variable_fingerprint="altered"),))
        other=PropertyRCAnalysisPlanAuthorityTests(methodName="runTest"); other.setUp()
        with self.assertRaisesRegex(QuantitativeAnalysisPlanError,"fingerprint|accepted"):
            other.create(planned_analyses=(bad,))

    def test_unresolved_and_pii_variables_cannot_enter_plan(self):
        missing=replace(self.binding,expected_variable_id="unknown")
        with self.assertRaisesRegex(QuantitativeAnalysisPlanError,"unavailable"):
            self.create(planned_analyses=(replace(self.analysis,variable_bindings=(missing,)),))
        actual=next(x for x in self.codebook.variables if x.variable_id==self.binding.actual_variable_id)
        pii=replace(actual,pii_classification=PiiClassification.PII_RESTRICTED)
        codebook=replace(self.codebook,variables=tuple(pii if x.variable_id==pii.variable_id else x for x in self.codebook.variables))
        with self.assertRaises(Exception): self.create(codebook=codebook)

    def test_coverage_is_distinct_and_partial_requires_explicit_authority(self):
        empty=self.create(version_id="empty",planned_analyses=())
        coverage=self.repository.get_coverage(empty.coverage_manifest_id,project_id=self.project)
        self.assertEqual(coverage.requirements[0].status,AnalysisPlanCoverageStatus.NOT_PLANNED)
        declaration=AnalysisPlanCoverageDeclaration("requirement-preference",AnalysisPlanCoverageStatus.PARTIALLY_PLANNED,"Only one reviewed component",False)
        other=PropertyRCAnalysisPlanAuthorityTests(methodName="runTest"); other.setUp()
        with self.assertRaisesRegex(QuantitativeAnalysisPlanError,"multi-component"):
            other.create(coverage_declarations=(declaration,))
        declared=replace(declaration,explicit_multi_component=True)
        value=other.create(coverage_declarations=(declared,),planned_analyses=())
        self.assertEqual(other.repository.get_coverage(value.coverage_manifest_id,project_id=other.project).requirements[0].status,AnalysisPlanCoverageStatus.PARTIALLY_PLANNED)

    def test_unsupported_inference_and_invalid_precursor_fail_closed(self):
        spec=ComparisonSpecification("cmp","INDEPENDENT_TWO_PROPORTION_Z_TEST",self.binding.actual_variable_id,self.binding.actual_variable_id,"1","2",alpha=Decimal("0.05"),sidedness="ONE_SIDED")
        planned=PlannedComparison("planned-cmp",spec,"",("analysis-brand","missing"),("question-preference",),("requirement-preference",),"SIGNIFICANCE")
        with self.assertRaisesRegex(QuantitativeAnalysisPlanError,"unsupported|precursor"):
            self.create(planned_comparisons=(planned,))

    def test_rejected_superseded_restart_corruption_and_dataset_only(self):
        draft=self.create(); review=self.service.submit_for_review(draft.version_id,project_id=self.project,run_id=self.run,new_version_id="review",actor_id="r",changed_at="later")
        self.service.reject(review.version_id,project_id=self.project,run_id=self.run,new_version_id="rejected",approval_id="rejection",expected_fingerprint=review.fingerprint,actor_id="owner",decided_at="x",rationale="not suitable")
        with self.assertRaises(QuantitativeAnalysisPlanError): self.service.resolve_current_approved(project_id=self.project,run_id=self.run,dataset=self.dataset,codebook=self.codebook)
        other=PropertyRCAnalysisPlanAuthorityTests(methodName="runTest"); other.setUp(); approved=other.approve()
        restarted=QuantitativeAnalysisPlanService(repository=QLQuantitativeAnalysisPlanRepository(QuantitativeStateService(repository=other.backing,digest_provider=other.digest)),research_design_service=other.service._designs,questionnaire_service=other.service._questionnaires,reconciliation_service=other.service._reconciliations,digest_provider=other.digest)
        self.assertEqual(restarted.resolve_current_approved(project_id=other.project,run_id=other.run,dataset=other.dataset,codebook=other.codebook).fingerprint,approved.fingerprint)
        other.service.supersede(approved.version_id,project_id=other.project,run_id=other.run,new_version_id="superseded",actor_id="owner",changed_at="later")
        with self.assertRaises(QuantitativeAnalysisPlanError): other.service.resolve_current_approved(project_id=other.project,run_id=other.run,dataset=other.dataset,codebook=other.codebook)
        mode=self.service.resolve_dataset_only(authority_id="dataset-only-rc",project_id=self.project,run_id=self.run)
        self.assertEqual(mode.status,"NO_DESIGN_AWARE_ANALYSIS_PLAN_AUTHORITY")

    def test_weighting_mode_revision_stales_current_plan_but_preserves_history(self):
        approved_plan = self.approve()
        designs = self.service._designs
        current_design = designs.resolve_current_approved(
            project_id=self.project, run_id=self.run
        )
        weighted_draft = designs.revise_design(
            current_design.version_id,
            project_id=self.project,
            run_id=self.run,
            version_id="design-weighted-draft",
            created_at="later",
            created_by="researcher",
            methodology_intent=replace(
                current_design.methodology_intent,
                weighting_intent="TARGET_MARGINS",
            ),
        )
        weighted_review = designs.submit_for_review(
            weighted_draft.version_id,
            project_id=self.project,
            run_id=self.run,
            new_version_id="design-weighted-review",
            actor_id="researcher",
            changed_at="later",
        )
        designs.approve(
            weighted_review.version_id,
            project_id=self.project,
            run_id=self.run,
            new_version_id="design-weighted-approved",
            approval_id="design-weighted-approval",
            expected_fingerprint=weighted_review.fingerprint,
            actor_id="owner",
            decided_at="latest",
            rationale="Weighting authority changed",
        )
        with self.assertRaisesRegex(Exception, "Research Design|current|stale"):
            self.service.resolve_current_approved(
                project_id=self.project,
                run_id=self.run,
                dataset=self.dataset,
                codebook=self.codebook,
            )
        self.assertEqual(
            self.repository.get_plan(approved_plan.version_id, project_id=self.project),
            approved_plan,
        )


if __name__=="__main__": unittest.main()

from pathlib import Path

from application.quantitative.dataset_import_service import QuantitativeDatasetImportService
from application.quantitative.measurement_reconciliation import QuantitativeMeasurementReconciliationService, _code
from application.quantitative.state_persistence import QuantitativeStateService
from dataclasses import replace
from decimal import Decimal

from application.quantitative.analysis_planning import QuantitativeAnalysisPlanService
from domain.quantitative.analysis import NpsAnalysisSpecification
from domain.quantitative.analysis_plan import AnalysisExecutionSupport, AnalysisWeightingPolicy, PlanVariableBinding, PlannedAnalysis
from domain.quantitative.dataset import DatasetFormat, VariableType
from domain.quantitative.measurement_reconciliation import (
    ReconciliationLifecycle, ReconciliationOverallStatus,
    ReconciliationMatchStatus, ReviewedMeasurementMapping,
    SemanticHookEquivalenceDecision,
)
from domain.quantitative.questionnaire_authority import ExpectedVariableBinding, QuestionnaireQuestion, QuestionnaireQuestionRole, QuestionnaireQuestionType, ScaleDefinition, ScaleInterpretation
from infrastructure.persistence.quantitative_analysis_plan_repository import QLQuantitativeAnalysisPlanRepository
from infrastructure.persistence.quantitative_measurement_reconciliation_repository import QLQuantitativeMeasurementReconciliationRepository
from infrastructure.quantitative.importers import SavPyreadstatAdapter
from infrastructure.quantitative.storage import InMemoryDatasetStorage
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.application.quantitative.test_property_ra_questionnaire_authority import PropertyRAQuestionnaireAuthorityTests


_SAV_BYTES = (Path(__file__).parents[2] / "fixtures" / "quantitative" / "rb_reconciliation.sav").read_bytes()


class PropertyRBRealSavReviewedTests(PropertyRAQuestionnaireAuthorityTests):
    def _nps_authority(self):
        revised=self.service._designs.revise_design(self.design.version_id,project_id=self.project,run_id=self.run,version_id="nps-design-draft",created_at="nps-design",created_by="researcher",analytical_requirements=(replace(self.design.analytical_requirements[0],requirement_type="NPS"),))
        review=self.service._designs.submit_for_review(revised.version_id,project_id=self.project,run_id=self.run,new_version_id="nps-design-review",actor_id="researcher",changed_at="nps-review")
        self.design=self.service._designs.approve(review.version_id,project_id=self.project,run_id=self.run,new_version_id="nps-design-approved",approval_id="nps-design-approval",expected_fingerprint=review.fingerprint,actor_id="owner",decided_at="nps-approved",rationale="Approved NPS analytical requirement")
        requirement=self.design.analytical_requirements[0].requirement_id
        scale=ScaleDefinition(Decimal("0"),Decimal("10"),tuple((Decimal(value),str(value)) for value in range(11)),ScaleInterpretation.NUMERIC)
        question=QuestionnaireQuestion("q-nps","section-main",QuestionnaireQuestionRole.SUBSTANTIVE,QuestionnaireQuestionType.NPS,"How likely are you to recommend?",None,None,(requirement,),None,True,(),scale,(),(),(ExpectedVariableBinding("ev-nps","nps"),),False,4,"team")
        questionnaire=self.approve(self.create(version_id="semantic-nps-questionnaire",questions=self.questions()+(question,),routes=()))
        digest=Sha256DigestProvider();state=QuantitativeStateService(repository=self.backing,digest_provider=digest)
        repository=QLQuantitativeMeasurementReconciliationRepository(state)
        imported=QuantitativeDatasetImportService(importers=(SavPyreadstatAdapter(),),storage=InMemoryDatasetStorage(),digest_provider=digest).import_bytes(_SAV_BYTES,filename="synthetic.sav",dataset_format=DatasetFormat.SAV,dataset_id="semantic-nps-sav",project_id=self.project,run_id=self.run)
        service=QuantitativeMeasurementReconciliationService(repository=repository,questionnaire_service=self.service,digest_provider=digest)
        candidate=service.create(reconciliation_id="semantic-nps-rb",version_id="semantic-nps-candidate",project_id=self.project,run_id=self.run,dataset=imported.dataset_version,codebook=imported.codebook,created_at="now",created_by="system")
        schema=self.service.derive_expected_measurement_schema(questionnaire.version_id,project_id=self.project)
        return questionnaire,digest,state,repository,imported,service,candidate,schema

    @staticmethod
    def _base_mapping(outcome, expected, actual):
        codes=tuple((str(code),str(code)) for code,_ in expected.value_labels)
        return ReviewedMeasurementMapping("decision-"+expected.expected_variable_id,expected.expected_variable_id,expected.fingerprint,actual.variable_id,actual.fingerprint,codes,(),codes,(),"owner","Questionnaire and SAV metadata reviewed","later","legacy-base-"+expected.expected_variable_id)

    def test_real_sav_reviewed_reconciliation_becomes_approved_authority(self):
        questionnaire=self.approve(self.create(version_id="real-sav-questionnaire",routes=()))
        digest=Sha256DigestProvider(); state=QuantitativeStateService(repository=self.backing,digest_provider=digest)
        repository=QLQuantitativeMeasurementReconciliationRepository(state)
        imported=QuantitativeDatasetImportService(importers=(SavPyreadstatAdapter(),),storage=InMemoryDatasetStorage(),digest_provider=digest).import_bytes(_SAV_BYTES,filename="synthetic.sav",dataset_format=DatasetFormat.SAV,dataset_id="real-sav",project_id=self.project,run_id=self.run)
        self.assertEqual(next(v for v in imported.codebook.variables if v.name=="nps").variable_type,VariableType.NUMERIC)
        service=QuantitativeMeasurementReconciliationService(repository=repository,questionnaire_service=self.service,digest_provider=digest)
        candidate=service.create(reconciliation_id="real-sav-rb",version_id="real-sav-candidate",project_id=self.project,run_id=self.run,dataset=imported.dataset_version,codebook=imported.codebook,created_at="now",created_by="system")
        self.assertEqual(candidate.overall_status,ReconciliationOverallStatus.REVIEW_REQUIRED)
        schema=self.service.derive_expected_measurement_schema(questionnaire.version_id,project_id=self.project)
        expected={item.expected_variable_id:item for item in schema.variables}; actual={item.variable_id:item for item in imported.codebook.variables}
        decisions=tuple(ReviewedMeasurementMapping("decision-"+item.expected_variable_id,item.expected_variable_id,item.expected_variable_fingerprint,item.actual_variable_id,item.actual_variable_fingerprint,(),(),(),(),"owner","Questionnaire and external SAV codebook reviewed","later","decision-fp-"+item.expected_variable_id) for item in candidate.variable_outcomes)
        reviewed=service.create(reconciliation_id="real-sav-rb",version_id="real-sav-reviewed",project_id=self.project,run_id=self.run,dataset=imported.dataset_version,codebook=imported.codebook,created_at="later",created_by="owner",reviewed_mappings=decisions,parent_version_id=candidate.version_id)
        approved=service.approve(reviewed.version_id,project_id=self.project,run_id=self.run,approval_id="real-sav-approval",expected_fingerprint=reviewed.fingerprint,actor_id="owner",decided_at="latest",rationale="Approved reviewed SAV mappings",dataset=imported.dataset_version,codebook=imported.codebook)
        self.assertEqual(approved.lifecycle_status,ReconciliationLifecycle.APPROVED)
        self.assertEqual(approved.overall_status,ReconciliationOverallStatus.APPROVED_WITH_MAPPINGS)
        self.assertIsNotNone(approved.questionnaire_snapshot_id)
        projection=service.accepted_projection(project_id=self.project,run_id=self.run,dataset=imported.dataset_version,codebook=imported.codebook)
        self.assertEqual(projection.reconciliation_fingerprint,approved.fingerprint)
        self.assertFalse(hasattr(projection,"respondent_rows"))

    def test_real_sav_nps_requires_explicit_semantic_review_then_rc_accepts_and_restart_preserves_it(self):
        questionnaire,digest,state,repository,imported,service,candidate,schema=self._nps_authority()
        nps_outcome=next(item for item in candidate.variable_outcomes if item.expected_variable_id=="ev-nps")
        self.assertEqual(nps_outcome.status,ReconciliationMatchStatus.REQUIRES_REVIEW)
        expected={item.expected_variable_id:item for item in schema.variables}
        actual={item.variable_id:item for item in imported.codebook.variables}
        nps_actual=actual[nps_outcome.actual_variable_id]
        rc=QuantitativeAnalysisPlanService(repository=QLQuantitativeAnalysisPlanRepository(state),research_design_service=self.service._designs,questionnaire_service=self.service,reconciliation_service=service,digest_provider=digest)
        planned=PlannedAnalysis("planned-nps",NpsAnalysisSpecification("spec-nps",nps_actual.variable_id),"",("objective-brand",),("question-preference",),("requirement-preference",),(PlanVariableBinding("ev-nps",nps_actual.variable_id,nps_actual.fingerprint),),"NPS","MANDATORY",AnalysisWeightingPolicy.UNWEIGHTED,None,None,(),(),AnalysisExecutionSupport.SUPPORTED)
        with self.assertRaisesRegex(Exception,"accepted reconciliation|not approved"):
            rc.create_draft(plan_id="blocked-nps-plan",version_id="blocked-nps-plan-v1",project_id=self.project,run_id=self.run,dataset=imported.dataset_version,codebook=imported.codebook,planned_analyses=(planned,),created_at="before-review",created_by="researcher")
        mappings=[]
        for outcome in candidate.variable_outcomes:
            mapping=self._base_mapping(outcome,expected[outcome.expected_variable_id],actual[outcome.actual_variable_id])
            if outcome.expected_variable_id=="ev-nps":
                mapping=service.review_semantic_hook_equivalence(candidate_version_id=candidate.version_id,project_id=self.project,run_id=self.run,dataset=imported.dataset_version,codebook=imported.codebook,expected_variable_id="ev-nps",actual_variable_id=outcome.actual_variable_id,expected_semantic_hook="NPS_SOURCE_0_10",decision=SemanticHookEquivalenceDecision.APPROVE_EQUIVALENCE,actor_id="owner",decided_at="reviewed",rationale="The approved questionnaire and source documentation identify this exact 0-10 variable as the NPS source",decision_id="nps-semantic-review",base_mapping=mapping)
            mappings.append(mapping)
        reviewed=service.create(reconciliation_id="semantic-nps-rb",version_id="semantic-nps-reviewed",project_id=self.project,run_id=self.run,dataset=imported.dataset_version,codebook=imported.codebook,created_at="reviewed",created_by="owner",reviewed_mappings=tuple(mappings),parent_version_id=candidate.version_id)
        self.assertEqual(next(item for item in reviewed.variable_outcomes if item.expected_variable_id=="ev-nps").status,ReconciliationMatchStatus.COMPATIBLE_MATCH)
        approved=service.approve(reviewed.version_id,project_id=self.project,run_id=self.run,approval_id="semantic-nps-approval",expected_fingerprint=reviewed.fingerprint,actor_id="owner",decided_at="approved",rationale="Approved exact reviewed SAV mappings",dataset=imported.dataset_version,codebook=imported.codebook)
        restarted=QuantitativeMeasurementReconciliationService(repository=QLQuantitativeMeasurementReconciliationRepository(QuantitativeStateService(repository=self.backing,digest_provider=digest)),questionnaire_service=self.service,digest_provider=digest)
        self.assertEqual(restarted.resolve_current_accepted(project_id=self.project,run_id=self.run,dataset=imported.dataset_version,codebook=imported.codebook).fingerprint,approved.fingerprint)
        rc=QuantitativeAnalysisPlanService(repository=QLQuantitativeAnalysisPlanRepository(state),research_design_service=self.service._designs,questionnaire_service=self.service,reconciliation_service=restarted,digest_provider=digest)
        plan=rc.create_draft(plan_id="nps-plan",version_id="nps-plan-v1",project_id=self.project,run_id=self.run,dataset=imported.dataset_version,codebook=imported.codebook,planned_analyses=(planned,),created_at="planned",created_by="researcher")
        self.assertEqual(plan.planned_analyses[0].variable_bindings[0].actual_variable_id,nps_actual.variable_id)
        semantic_mapping=next(item for item in mappings if item.expected_variable_id=="ev-nps")
        self.assertFalse(hasattr(semantic_mapping.semantic_hook_equivalences[0],"respondent_rows"))

    def test_numeric_code_normalization_is_lossless_and_deterministic(self):
        self.assertEqual({_code("1"),_code(1),_code(1.0)},{"1"})
        self.assertEqual(_code("1.5"),_code(1.5))
        self.assertNotEqual(_code("1.5"),_code("1.50x"))

    def test_semantic_hook_review_rejects_wrong_stale_conflicting_and_structurally_invalid_authority(self):
        _,_,_,_,imported,service,candidate,schema=self._nps_authority()
        expected=next(item for item in schema.variables if item.expected_variable_id=="ev-nps")
        outcome=next(item for item in candidate.variable_outcomes if item.expected_variable_id=="ev-nps")
        actual=next(item for item in imported.codebook.variables if item.variable_id==outcome.actual_variable_id)
        base=self._base_mapping(outcome,expected,actual)
        values=dict(candidate_version_id=candidate.version_id,project_id=self.project,run_id=self.run,dataset=imported.dataset_version,codebook=imported.codebook,expected_variable_id=expected.expected_variable_id,actual_variable_id=actual.variable_id,expected_semantic_hook="NPS_SOURCE_0_10",actor_id="owner",decided_at="reviewed",rationale="Exact source-document semantic review",decision_id="semantic-decision",base_mapping=base)
        rejected=service.review_semantic_hook_equivalence(**values,decision=SemanticHookEquivalenceDecision.REJECT_EQUIVALENCE)
        rejected_version=service.create(reconciliation_id="semantic-nps-rb",version_id="semantic-rejected",project_id=self.project,run_id=self.run,dataset=imported.dataset_version,codebook=imported.codebook,created_at="reviewed",created_by="owner",reviewed_mappings=(rejected,),parent_version_id=candidate.version_id)
        self.assertEqual(next(item for item in rejected_version.variable_outcomes if item.expected_variable_id=="ev-nps").status,ReconciliationMatchStatus.REQUIRES_REVIEW)
        approved=service.review_semantic_hook_equivalence(**values,decision=SemanticHookEquivalenceDecision.APPROVE_EQUIVALENCE)
        with self.assertRaisesRegex(Exception,"conflicting"):
            service.review_semantic_hook_equivalence(**{**values,"base_mapping":approved,"decision_id":"other"},decision=SemanticHookEquivalenceDecision.REJECT_EQUIVALENCE)
        with self.assertRaisesRegex(Exception,"unknown expected hook"):
            service.review_semantic_hook_equivalence(**{**values,"expected_semantic_hook":"SATISFACTION_0_10"},decision=SemanticHookEquivalenceDecision.APPROVE_EQUIVALENCE)
        incompatible=replace(actual,variable_type=VariableType.CATEGORICAL,fingerprint="incompatible-variable")
        incompatible_codebook=replace(imported.codebook,variables=tuple(incompatible if item.variable_id==actual.variable_id else item for item in imported.codebook.variables),fingerprint="incompatible-codebook")
        incompatible_dataset=replace(imported.dataset_version,codebook_fingerprint=incompatible_codebook.fingerprint)
        incompatible_candidate=service.create(reconciliation_id="semantic-nps-rb-incompatible",version_id="semantic-nps-incompatible-candidate",project_id=self.project,run_id=self.run,dataset=incompatible_dataset,codebook=incompatible_codebook,created_at="incompatible",created_by="system")
        with self.assertRaisesRegex(Exception,"structural incompatibility"):
            service.review_semantic_hook_equivalence(**{**values,"candidate_version_id":incompatible_candidate.version_id,"dataset":incompatible_dataset,"codebook":incompatible_codebook,"base_mapping":replace(base,actual_variable_fingerprint=incompatible.fingerprint),"decision_id":"incompatible"},decision=SemanticHookEquivalenceDecision.APPROVE_EQUIVALENCE)
        stale_codebook=replace(imported.codebook,fingerprint="changed-codebook")
        stale_dataset=replace(imported.dataset_version,codebook_fingerprint=stale_codebook.fingerprint)
        with self.assertRaisesRegex(Exception,"stale"):
            service.create(reconciliation_id="semantic-nps-rb",version_id="semantic-stale",project_id=self.project,run_id=self.run,dataset=stale_dataset,codebook=stale_codebook,created_at="later",created_by="owner",reviewed_mappings=(approved,),parent_version_id=candidate.version_id)

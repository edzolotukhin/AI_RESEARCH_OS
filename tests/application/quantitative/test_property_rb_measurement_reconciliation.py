from dataclasses import replace
import unittest

from application.quantitative.measurement_reconciliation import QuantitativeMeasurementReconciliationService
from application.quantitative.state_persistence import QuantitativeStateService
from domain.quantitative.dataset import CodebookVersion, DatasetFormat, DatasetVersion, DatasetVersionKind, MissingValueRule, ValidationStatus, VariableDefinition
from domain.quantitative.measurement_reconciliation import ReconciliationLifecycle, ReconciliationMatchStatus
from infrastructure.persistence.quantitative_measurement_reconciliation_repository import QLQuantitativeMeasurementReconciliationRepository
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.application.quantitative.test_property_ra_questionnaire_authority import PropertyRAQuestionnaireAuthorityTests

class PropertyRBMeasurementReconciliationTests(unittest.TestCase):
    def setUp(self):
        ra=PropertyRAQuestionnaireAuthorityTests(methodName="runTest"); ra.setUp()
        self.questionnaire=ra.approve(); self.project,self.run=ra.project,ra.run
        self.schema=ra.service.derive_expected_measurement_schema(self.questionnaire.version_id,project_id=self.project)
        self.digest=Sha256DigestProvider(); self.backing=ra.backing
        state=QuantitativeStateService(repository=self.backing,digest_provider=self.digest)
        self.repository=QLQuantitativeMeasurementReconciliationRepository(state)
        self.service=QuantitativeMeasurementReconciliationService(repository=self.repository,questionnaire_service=ra.service,digest_provider=self.digest)
        variables=[]
        for expected in self.schema.variables:
            missing=tuple(MissingValueRule("value",value=x.code) for x in expected.missing_value_rules)
            variables.append(VariableDefinition("actual-"+expected.expected_variable_id,expected.variable_name,expected.label,expected.variable_type,expected.analytical_role,expected.measurement_level,tuple(expected.value_labels),missing,expected.pii_expectation,expected.multiple_response_set_id,expected.semantic_hooks,fingerprint="actual-fp-"+expected.expected_variable_id,metadata_provenance=(("type","EXPLICITLY_RESOLVED"),("role","EXPLICITLY_RESOLVED"),("pii","EXPLICITLY_RESOLVED"),("mr","SOURCE_DECLARED" if expected.multiple_response_set_id else "ABSENT"))))
        self.codebook=CodebookVersion("codebook",tuple(variables),"codebook-fp")
        self.dataset=DatasetVersion("dataset","dataset-v1",self.project,self.run,DatasetVersionKind.RAW,"file","synthetic.sav","file-fp",DatasetFormat.SAV,10,len(variables),"schema-fp","codebook","codebook-fp","data-fp","dataset-fp",self.codebook.variables[0].pii_classification,ValidationStatus.VALID,"protected","test","1")

    def create(self, **kwargs):
        return self.service.create(reconciliation_id="reconciliation",version_id=kwargs.pop("version_id","reconciliation-v1"),project_id=self.project,run_id=self.run,dataset=kwargs.pop("dataset",self.dataset),codebook=kwargs.pop("codebook",self.codebook),created_at="now",created_by="owner",**kwargs)

    def test_exact_reconciliation_is_deterministic_restart_safe_and_payload_safe(self):
        first=self.create()
        self.assertEqual(first.lifecycle_status,ReconciliationLifecycle.APPROVED)
        self.assertTrue(all(x.status is ReconciliationMatchStatus.EXACT_MATCH for x in first.variable_outcomes))
        self.assertFalse(hasattr(first,"respondent_rows"))
        restarted=QuantitativeMeasurementReconciliationService(repository=QLQuantitativeMeasurementReconciliationRepository(QuantitativeStateService(repository=self.backing,digest_provider=self.digest)),questionnaire_service=self.service._questionnaires,digest_provider=self.digest)
        self.assertEqual(restarted.resolve_current_accepted(project_id=self.project,run_id=self.run,dataset=self.dataset,codebook=self.codebook).fingerprint,first.fingerprint)

    def test_rename_missing_pii_and_dataset_staleness_fail_closed(self):
        renamed=replace(self.codebook.variables[0],name="renamed")
        value=self.create(version_id="renamed",codebook=replace(self.codebook,variables=(renamed,)+self.codebook.variables[1:]))
        self.assertIn(ReconciliationMatchStatus.MISSING_IN_DATA,{x.status for x in value.variable_outcomes})
        with self.assertRaisesRegex(Exception,"not approved|stale"):
            self.service.resolve_current_accepted(project_id=self.project,run_id=self.run,dataset=replace(self.dataset,version_id="new"),codebook=self.codebook)

    def test_dataset_only_has_explicit_absence(self):
        value=self.service.resolve_dataset_only(authority_id="dataset-only-rb",project_id=self.project,run_id=self.run)
        self.assertEqual(value.status,"NO_QUESTIONNAIRE_RECONCILIATION_AUTHORITY")

if __name__ == "__main__": unittest.main()

import os
import tempfile

import pandas as pd
import pyreadstat

from application.quantitative.dataset_import_service import QuantitativeDatasetImportService
from application.quantitative.measurement_reconciliation import QuantitativeMeasurementReconciliationService
from application.quantitative.state_persistence import QuantitativeStateService
from domain.quantitative.dataset import DatasetFormat, VariableType
from domain.quantitative.measurement_reconciliation import (
    ReconciliationLifecycle, ReconciliationOverallStatus,
    ReviewedMeasurementMapping,
)
from infrastructure.persistence.quantitative_measurement_reconciliation_repository import QLQuantitativeMeasurementReconciliationRepository
from infrastructure.quantitative.importers import SavPyreadstatAdapter
from infrastructure.quantitative.storage import InMemoryDatasetStorage
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.application.quantitative.test_property_ra_questionnaire_authority import PropertyRAQuestionnaireAuthorityTests


def _sav_bytes():
    frame=pd.DataFrame({"sex":[1,2,1,2],"age":[24,35,48,29],"region":[1,2,3,1],"categorical":[1,2,1,2],"numeric":[7.,8.,6.,9.],"nps":[8,9,6,10],"brand_preference":[1,2,1,2],"quality_check":[2,2,2,2],"routing_group":[1,2,1,2]})
    labels={"sex":{1:"Group A",2:"Group B"},"region":{1:"West",2:"Center",3:"East"},"categorical":{1:"Yes",2:"No"},"nps":{i:str(i) for i in range(11)},"brand_preference":{1:"Brand A",2:"Brand B"},"quality_check":{1:"First",2:"Second"},"routing_group":{1:"A",2:"B"}}
    measures={name:("nominal" if name in labels and name != "nps" else "scale") for name in frame.columns}
    handle,path=tempfile.mkstemp(suffix=".sav"); os.close(handle)
    try:
        pyreadstat.write_sav(frame,path,column_labels={name:name for name in frame.columns},variable_value_labels=labels,variable_measure=measures,missing_ranges={"categorical":[{"lo":9,"hi":9}]})
        with open(path,"rb") as stream: return stream.read()
    finally: os.unlink(path)


class PropertyRBRealSavReviewedTests(PropertyRAQuestionnaireAuthorityTests):
    def test_real_sav_reviewed_reconciliation_becomes_approved_authority(self):
        questionnaire=self.approve(self.create(version_id="real-sav-questionnaire",routes=()))
        digest=Sha256DigestProvider(); state=QuantitativeStateService(repository=self.backing,digest_provider=digest)
        repository=QLQuantitativeMeasurementReconciliationRepository(state)
        imported=QuantitativeDatasetImportService(importers=(SavPyreadstatAdapter(),),storage=InMemoryDatasetStorage(),digest_provider=digest).import_bytes(_sav_bytes(),filename="synthetic.sav",dataset_format=DatasetFormat.SAV,dataset_id="real-sav",project_id=self.project,run_id=self.run)
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

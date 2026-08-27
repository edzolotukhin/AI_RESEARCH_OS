import tempfile
import unittest
from dataclasses import replace

from application.quantitative.state_persistence import QuantitativePersistenceError,QuantitativeStateService
from application.quantitative.study_sufficiency import QuantitativeStudySufficiencyService
from infrastructure.persistence.memory.in_memory_quantitative_state_repository import InMemoryQuantitativeStateRepository
from infrastructure.persistence.quantitative_study_sufficiency_repository import QLQuantitativeStudySufficiencyRepository
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.api.helpers import build_test_container

class PropertyRJPersistenceCompositionTests(unittest.TestCase):
    def test_typed_ql_restart_idempotency_wrong_project_and_corruption(self):
        records=InMemoryQuantitativeStateRepository();digest=Sha256DigestProvider();state=QuantitativeStateService(repository=records,digest_provider=digest);repo=QLQuantitativeStudySufficiencyRepository(state)
        service=QuantitativeStudySufficiencyService(repository=repo,digest_provider=digest,authority_chain_selection_service=None,research_design_service=None,objective_coverage_service=None)
        value=service.dataset_only_absence(project_id="p",run_id="r")
        self.assertEqual(value,service.dataset_only_absence(project_id="p",run_id="r"))
        self.assertIsNone(repo._get(value.absence_id,"wrong",type(value)))
        record=records._records[value.absence_id];records._records[value.absence_id]=replace(record,payload_checksum="corrupt")
        with self.assertRaisesRegex(QuantitativePersistenceError,"checksum"):state.load(value.absence_id,project_id="p")

    def test_production_composition_uses_real_rk_boundary(self):
        with tempfile.TemporaryDirectory() as root:
            container=build_test_container(temp_dir=root)
            try:
                rj=container.quantitative_study_sufficiency_service
                self.assertIsInstance(rj,QuantitativeStudySufficiencyService)
                self.assertIs(rj._rk,container.quantitative_authority_chain_selection_service)
                self.assertIsNotNone(container.quantitative_authority_chain_service)
            finally:container.shutdown()

if __name__=="__main__":unittest.main()

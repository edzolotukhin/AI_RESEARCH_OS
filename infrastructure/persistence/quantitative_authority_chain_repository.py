from application.quantitative.state_persistence import QuantitativePersistenceError
from domain.quantitative.authority_chain import QuantitativeDesignAwareAuthorityChainManifest


class QLQuantitativeAuthorityChainRepository:
    def __init__(self, state_service):
        self._state = state_service

    def save_manifest(self, value):
        try:
            self._state.persist(value, record_id=value.manifest_id, project_id=value.project_id,
                                run_id=value.run_id, accepted=True)
            return value
        except ValueError:
            existing = self.get_manifest(value.manifest_id, project_id=value.project_id)
            if existing != value:
                raise QuantitativePersistenceError("conflicting deterministic authority-chain manifest")
            return existing

    def get_manifest(self, manifest_id, *, project_id):
        try:
            return self._state.load(manifest_id, project_id=project_id,
                                    expected_type=QuantitativeDesignAwareAuthorityChainManifest)
        except QuantitativePersistenceError as exc:
            if "unavailable for project" in str(exc):
                return None
            raise

    def list_manifests(self, *, project_id, run_id):
        return self._state.list_for_run(run_id, project_id=project_id,
                                        expected_type=QuantitativeDesignAwareAuthorityChainManifest)

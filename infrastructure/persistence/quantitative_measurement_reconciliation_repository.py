from application.quantitative.state_persistence import QuantitativePersistenceError
from domain.quantitative.measurement_reconciliation import *
from domain.quantitative.quality import QuestionnaireSnapshot

class QLQuantitativeMeasurementReconciliationRepository:
    def __init__(self, state_service): self._state = state_service
    def save_reconciliation(self, value, *, run_id): self._state.persist(value, record_id=value.version_id, project_id=value.project_id, run_id=run_id, parent_record_id=value.parent_version_id, accepted=value.lifecycle_status is ReconciliationLifecycle.APPROVED)
    def save_mapping_decision(self, value, *, project_id, run_id): self._state.persist(value, record_id=value.decision_id, project_id=project_id, run_id=run_id, accepted=True)
    def save_approval(self, value, *, run_id): self._state.persist(value, record_id=value.approval_id, project_id=value.project_id, run_id=run_id, parent_record_id=value.reconciliation_version_id, accepted=value.decision is ReconciliationApprovalDecision.APPROVED)
    def save_availability(self, value, *, run_id): self._state.persist(value, record_id=value.manifest_id, project_id=value.project_id, run_id=run_id)
    def save_snapshot(self, value, *, project_id, run_id, parent_id): self._state.persist(value, record_id=value.snapshot_id, project_id=project_id, run_id=run_id, parent_record_id=parent_id)
    def save_dataset_only(self, value): self._state.persist(value, record_id=value.authority_id, project_id=value.project_id, run_id=value.run_id, accepted=True)
    def _load(self, record_id, project_id, expected):
        try: return self._state.load(record_id, project_id=project_id, expected_type=expected)
        except QuantitativePersistenceError as exc:
            if "unavailable for project" in str(exc): return None
            raise
    def get_reconciliation(self, version_id, *, project_id): return self._load(version_id, project_id, QuantitativeMeasurementReconciliationVersion)
    def get_mapping_decision(self, decision_id, *, project_id): return self._load(decision_id, project_id, ReviewedMeasurementMapping)
    def get_approval(self, approval_id, *, project_id): return self._load(approval_id, project_id, QuantitativeMeasurementReconciliationApproval)
    def get_availability(self, manifest_id, *, project_id): return self._load(manifest_id, project_id, MeasurementDataAvailabilityManifest)
    def get_snapshot(self, snapshot_id, *, project_id): return self._load(snapshot_id, project_id, QuestionnaireSnapshot)
    def list_reconciliations(self, *, project_id, run_id): return tuple(sorted(self._state.list_for_run(run_id, project_id=project_id, expected_type=QuantitativeMeasurementReconciliationVersion), key=lambda x: x.version_sequence))

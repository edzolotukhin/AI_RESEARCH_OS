from application.quantitative.state_persistence import QuantitativePersistenceError
from domain.quantitative.report_lineage import (
    DatasetOnlyReportLineageAbsence,
    DesignAwareReportInputAuthority,
    QuantitativeReportCoverageManifest,
    QuantitativeReportDesignLineageManifest,
)


class QLQuantitativeReportLineageRepository:
    def __init__(self, state_service):
        self._state = state_service

    def _save(self, value, record_id, expected):
        try:
            self._state.persist(value, record_id=record_id, project_id=value.project_id, run_id=value.run_id, accepted=True)
            return value
        except ValueError:
            existing = self._state.load(record_id, project_id=value.project_id, expected_type=expected)
            if existing != value:
                raise QuantitativePersistenceError("conflicting deterministic Quantitative Report lineage authority")
            return existing

    def _get(self, record_id, project_id, expected):
        try:
            return self._state.load(record_id, project_id=project_id, expected_type=expected)
        except QuantitativePersistenceError as exc:
            if "unavailable for project" in str(exc):
                return None
            raise

    def save_input_authority(self, value): return self._save(value, value.authority_id, DesignAwareReportInputAuthority)
    def get_input_authority(self, authority_id, *, project_id): return self._get(authority_id, project_id, DesignAwareReportInputAuthority)
    def save_coverage(self, value): return self._save(value, value.coverage_id, QuantitativeReportCoverageManifest)
    def get_coverage(self, coverage_id, *, project_id): return self._get(coverage_id, project_id, QuantitativeReportCoverageManifest)
    def save_manifest(self, value): return self._save(value, value.manifest_id, QuantitativeReportDesignLineageManifest)
    def get_manifest(self, manifest_id, *, project_id): return self._get(manifest_id, project_id, QuantitativeReportDesignLineageManifest)

    def find_manifest_for_input(self, input_authority_id, *, project_id, run_id):
        matches = tuple(item for item in self._state.list_for_run(run_id, project_id=project_id, expected_type=QuantitativeReportDesignLineageManifest) if item.input_authority_id == input_authority_id)
        if len(matches) > 1: raise QuantitativePersistenceError("duplicate Report lineage manifests")
        return matches[0] if matches else None

    def find_coverage_for_input(self, input_authority_id, *, project_id, run_id):
        matches = tuple(item for item in self._state.list_for_run(run_id, project_id=project_id, expected_type=QuantitativeReportCoverageManifest) if item.input_authority_id == input_authority_id)
        if len(matches) > 1: raise QuantitativePersistenceError("duplicate Report coverage manifests")
        return matches[0] if matches else None

    def save_dataset_only_absence(self, value): return self._save(value, value.absence_id, DatasetOnlyReportLineageAbsence)

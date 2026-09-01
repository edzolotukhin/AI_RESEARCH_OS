from application.quantitative.state_persistence import QuantitativePersistenceError
from domain.quantitative.insight_lineage import (
    DatasetOnlyInsightLineageAbsence, DesignAwareInsightControlledAbsence,
    DesignAwareInsightInputAuthority,
    QuantitativeInsightCoverageManifest, QuantitativeInsightDesignLineageManifest,
)


class QLQuantitativeInsightLineageRepository:
    def __init__(self, state_service): self._state = state_service

    def _save(self, value, record_id, expected):
        try:
            self._state.persist(value, record_id=record_id, project_id=value.project_id, run_id=value.run_id, accepted=True)
            return value
        except ValueError:
            existing = self._state.load(record_id, project_id=value.project_id, expected_type=expected)
            if existing != value:
                raise QuantitativePersistenceError("conflicting deterministic Quantitative Insight lineage authority")
            return existing

    def _get(self, record_id, project_id, expected):
        try: return self._state.load(record_id, project_id=project_id, expected_type=expected)
        except QuantitativePersistenceError as exc:
            if "unavailable for project" in str(exc): return None
            raise

    def save_input_authority(self, value): return self._save(value, value.authority_id, DesignAwareInsightInputAuthority)
    def get_input_authority(self, authority_id, *, project_id): return self._get(authority_id, project_id, DesignAwareInsightInputAuthority)
    def save_coverage(self, value): return self._save(value, value.coverage_id, QuantitativeInsightCoverageManifest)
    def get_coverage(self, coverage_id, *, project_id): return self._get(coverage_id, project_id, QuantitativeInsightCoverageManifest)
    def save_manifest(self, value): return self._save(value, value.manifest_id, QuantitativeInsightDesignLineageManifest)
    def get_manifest(self, manifest_id, *, project_id): return self._get(manifest_id, project_id, QuantitativeInsightDesignLineageManifest)

    def find_manifest_for_input(self, input_authority_id, *, project_id, run_id):
        matches = tuple(item for item in self._state.list_for_run(run_id, project_id=project_id, expected_type=QuantitativeInsightDesignLineageManifest) if item.input_authority_id == input_authority_id)
        if len(matches) > 1: raise QuantitativePersistenceError("duplicate Insight lineage manifests")
        return matches[0] if matches else None

    def save_dataset_only_absence(self, value): return self._save(value, value.absence_id, DatasetOnlyInsightLineageAbsence)
    def save_controlled_absence(self, value): return self._save(value, value.absence_id, DesignAwareInsightControlledAbsence)
    def get_controlled_absence(self, absence_id, *, project_id): return self._get(absence_id, project_id, DesignAwareInsightControlledAbsence)

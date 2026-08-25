from __future__ import annotations

from application.quantitative.state_persistence import QuantitativePersistenceError, QuantitativeStateService
from domain.quantitative.research_design_authority import (
    DatasetOnlyResearchAuthority, QuantitativeResearchDesignApproval,
    QuantitativeResearchDesignVersion, QuantitativeStudyBriefVersion,
    QuantitativeTraceabilityManifest,
)


class QLQuantitativeResearchDesignRepository:
    """Dedicated QZ repository backed by typed QL state records."""

    def __init__(self, state_service: QuantitativeStateService) -> None:
        self._state = state_service

    def save_brief(self, value, *, run_id):
        self._state.persist(value, record_id=value.version_id, project_id=value.project_id, run_id=run_id, parent_record_id=value.parent_version_id)

    def save_design(self, value, *, run_id):
        self._state.persist(value, record_id=value.version_id, project_id=value.project_id, run_id=run_id, parent_record_id=value.parent_version_id, accepted=value.lifecycle_status.value == "APPROVED")

    def save_approval(self, value, *, run_id):
        self._state.persist(value, record_id=value.approval_id, project_id=value.project_id, run_id=run_id, parent_record_id=value.design_version_id, accepted=value.decision.value == "APPROVED")

    def save_manifest(self, value, *, run_id):
        self._state.persist(value, record_id=value.manifest_id, project_id=value.project_id, run_id=run_id, parent_record_id=value.design_version_id)

    def save_dataset_only(self, value):
        self._state.persist(value, record_id=value.authority_id, project_id=value.project_id, run_id=value.run_id, accepted=True)

    def _load(self, record_id, project_id, expected_type):
        try:
            return self._state.load(record_id, project_id=project_id, expected_type=expected_type)
        except QuantitativePersistenceError as exc:
            if "unavailable for project" in str(exc): return None
            raise

    def get_brief(self, version_id, *, project_id): return self._load(version_id, project_id, QuantitativeStudyBriefVersion)
    def get_design(self, version_id, *, project_id): return self._load(version_id, project_id, QuantitativeResearchDesignVersion)
    def get_approval(self, approval_id, *, project_id): return self._load(approval_id, project_id, QuantitativeResearchDesignApproval)
    def get_manifest(self, manifest_id, *, project_id): return self._load(manifest_id, project_id, QuantitativeTraceabilityManifest)
    def get_dataset_only(self, authority_id, *, project_id): return self._load(authority_id, project_id, DatasetOnlyResearchAuthority)

    def list_briefs(self, *, project_id, run_id):
        return tuple(sorted(self._state.list_for_run(run_id, project_id=project_id, expected_type=QuantitativeStudyBriefVersion), key=lambda item: item.version_sequence))

    def list_designs(self, *, project_id, run_id):
        return tuple(sorted(self._state.list_for_run(run_id, project_id=project_id, expected_type=QuantitativeResearchDesignVersion), key=lambda item: item.version_sequence))

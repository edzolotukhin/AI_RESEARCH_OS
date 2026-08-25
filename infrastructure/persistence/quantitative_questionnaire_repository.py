from __future__ import annotations

from application.quantitative.state_persistence import QuantitativePersistenceError, QuantitativeStateService
from domain.quantitative.questionnaire_authority import (
    DatasetOnlyQuestionnaireAuthority, ExpectedMeasurementSchema,
    QuestionnaireDesignCoverageManifest, QuestionnaireValidationManifest,
    QuantitativeQuestionnaireApproval, QuantitativeQuestionnaireVersion,
)


class QLQuantitativeQuestionnaireRepository:
    def __init__(self, state_service: QuantitativeStateService) -> None:
        self._state = state_service

    def save_questionnaire(self, value, *, run_id):
        self._state.persist(value, record_id=value.version_id, project_id=value.project_id, run_id=run_id, parent_record_id=value.parent_version_id, accepted=value.lifecycle_status.value == "APPROVED")

    def save_approval(self, value, *, run_id):
        self._state.persist(value, record_id=value.approval_id, project_id=value.project_id, run_id=run_id, parent_record_id=value.questionnaire_version_id, accepted=value.decision.value == "APPROVED")

    def save_schema(self, value, *, run_id):
        self._state.persist(value, record_id=value.schema_id, project_id=value.project_id, run_id=run_id, parent_record_id=value.questionnaire_version_id)

    def save_validation(self, value, *, run_id):
        self._state.persist(value, record_id=value.manifest_id, project_id=value.project_id, run_id=run_id, parent_record_id=value.questionnaire_version_id, accepted=value.valid)

    def save_coverage(self, value, *, run_id):
        self._state.persist(value, record_id=value.manifest_id, project_id=value.project_id, run_id=run_id, parent_record_id=value.questionnaire_version_id)

    def save_dataset_only(self, value):
        self._state.persist(value, record_id=value.authority_id, project_id=value.project_id, run_id=value.run_id, accepted=True)

    def _load(self, record_id, project_id, expected_type):
        try:
            return self._state.load(record_id, project_id=project_id, expected_type=expected_type)
        except QuantitativePersistenceError as exc:
            if "unavailable for project" in str(exc): return None
            raise

    def get_questionnaire(self, version_id, *, project_id): return self._load(version_id, project_id, QuantitativeQuestionnaireVersion)
    def get_approval(self, approval_id, *, project_id): return self._load(approval_id, project_id, QuantitativeQuestionnaireApproval)
    def get_schema(self, schema_id, *, project_id): return self._load(schema_id, project_id, ExpectedMeasurementSchema)
    def get_validation(self, manifest_id, *, project_id): return self._load(manifest_id, project_id, QuestionnaireValidationManifest)
    def get_coverage(self, manifest_id, *, project_id): return self._load(manifest_id, project_id, QuestionnaireDesignCoverageManifest)
    def get_dataset_only(self, authority_id, *, project_id): return self._load(authority_id, project_id, DatasetOnlyQuestionnaireAuthority)

    def list_questionnaires(self, *, project_id, run_id):
        return tuple(sorted(self._state.list_for_run(run_id, project_id=project_id, expected_type=QuantitativeQuestionnaireVersion), key=lambda item: item.version_sequence))

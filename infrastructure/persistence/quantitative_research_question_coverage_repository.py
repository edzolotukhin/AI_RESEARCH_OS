from application.quantitative.state_persistence import QuantitativePersistenceError
from domain.quantitative.research_question_coverage import (
    DatasetOnlyResearchQuestionCoverageAbsence,
    QuantitativeResearchQuestionCoverageApproval,
    QuantitativeResearchQuestionCoverageAssessmentVersion,
    QuantitativeResearchQuestionCoverageRunManifest,
)


class QLQuantitativeResearchQuestionCoverageRepository:
    def __init__(self, state_service):
        self._state = state_service

    def _save(self, value, record_id, expected):
        try:
            self._state.persist(value, record_id=record_id, project_id=value.project_id, run_id=value.run_id, accepted=True)
            return value
        except ValueError:
            existing = self._state.load(record_id, project_id=value.project_id, expected_type=expected)
            if existing != value:
                raise QuantitativePersistenceError("conflicting deterministic ResearchQuestion coverage authority")
            return existing

    def _get(self, record_id, project_id, expected):
        try:
            return self._state.load(record_id, project_id=project_id, expected_type=expected)
        except QuantitativePersistenceError as exc:
            if "unavailable for project" in str(exc):
                return None
            raise

    def save_assessment(self, value):
        return self._save(value, value.version_id, QuantitativeResearchQuestionCoverageAssessmentVersion)

    def get_assessment(self, version_id, *, project_id):
        return self._get(version_id, project_id, QuantitativeResearchQuestionCoverageAssessmentVersion)

    def list_assessments(self, *, project_id, run_id):
        return tuple(sorted(self._state.list_for_run(run_id, project_id=project_id, expected_type=QuantitativeResearchQuestionCoverageAssessmentVersion), key=lambda item: item.version_sequence))

    def save_run_manifest(self, value):
        return self._save(value, value.manifest_id, QuantitativeResearchQuestionCoverageRunManifest)

    def get_run_manifest(self, manifest_id, *, project_id):
        return self._get(manifest_id, project_id, QuantitativeResearchQuestionCoverageRunManifest)
    def save_approval(self, value):
        return self._save(value, value.approval_id, QuantitativeResearchQuestionCoverageApproval)

    def get_approval(self, approval_id, *, project_id):
        return self._get(approval_id, project_id, QuantitativeResearchQuestionCoverageApproval)

    def save_dataset_only_absence(self, value):
        return self._save(value, value.absence_id, DatasetOnlyResearchQuestionCoverageAbsence)

from __future__ import annotations

from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from application.quantitative.state_persistence import (
    QuantitativePersistenceError,
    validate_recovered_analysis_linkage,
)
from application.quantitative.workflow import (
    QuantitativeApprovalService,
    QuantitativeWorkflowError,
)
from domain.quantitative.dataset import DatasetVersion
from domain.quantitative.quality import QualityControlRun
from domain.quantitative.weighting import WeightSet
from domain.quantitative.workflow import QuantitativeStudyProjection
from domain.workflow_status import WorkflowStatus
from tests.api.helpers import ApiTestCase
from tests.application.quantitative.test_property_qa_byte_to_statistic_provenance import (
    xlsx_bytes,
)
from tests.fixtures.quantitative.sav_sample_fixture import sav_sample_bytes


class PropertyQuSameStudyDatasetReplacementTests(ApiTestCase):
    def _principal(self) -> str:
        return self.container.authentication_service.authenticate_api_key(
            self.container._test_api_key_plaintext
        ).principal_id

    def _create_with_sav(self, key: str) -> tuple[str, QuantitativeStudyProjection]:
        created = self.client.post(
            "/ui/quantitative/studies",
            data={
                "title": "QU replacement acceptance",
                "description": "synthetic only",
                "submission_key": key,
            },
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 303)
        study_id = created.headers["location"].rsplit("/", 1)[-1]
        uploaded = self.client.post(
            f"/ui/quantitative/studies/{study_id}/dataset",
            files={
                "dataset": (
                    "initial.sav",
                    sav_sample_bytes(),
                    "application/octet-stream",
                )
            },
            follow_redirects=False,
        )
        self.assertEqual(uploaded.status_code, 303)
        return study_id, self._study(study_id)

    def _study(self, study_id: str) -> QuantitativeStudyProjection:
        return self.container.quantitative_ui_service.get(
            study_id, owner_id=self._principal()
        )

    @staticmethod
    def _replacement_bytes() -> bytes:
        return xlsx_bytes(
            ["respondent_id", "sex", "age", "region", "choice", "score", "nps"],
            [
                ["r1", "F", "18-34", "North", "A", 7, 10],
                ["r2", "M", "35-54", "South", "B", 6, 8],
                ["r3", "F", "35-54", "North", "A", 8, 9],
                ["r4", "M", "18-34", "South", "B", 5, 6],
            ],
        )

    def _replace(self, study_id: str, content: bytes | None = None):
        return self.client.post(
            f"/ui/quantitative/studies/{study_id}/dataset",
            data={"replace_existing": "true"},
            files={
                "dataset": (
                    "replacement.xlsx",
                    content if content is not None else self._replacement_bytes(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            follow_redirects=False,
        )

    def _approved_old_authority(self, study_id: str):
        self.client.post(
            f"/ui/quantitative/studies/{study_id}/qc", follow_redirects=False
        )
        self.client.post(
            f"/ui/quantitative/studies/{study_id}/cleaning",
            data={
                "variable_name": "mynum",
                "replacements_json": json.dumps(
                    {"1.1": 0, "1.2": 7, "-1000.3": 8, "-1.4": 9, "1000.3": 10}
                ),
            },
            follow_redirects=False,
        )
        study = self._study(study_id)
        self.client.post(
            f"/ui/quantitative/studies/{study_id}/qc-approval",
            data={
                "fingerprint": study.qc_record_id.rsplit(":", 1)[-1],
                "decision": "APPROVED",
                "rationale": "old dataset QC",
            },
            follow_redirects=False,
        )
        self.client.post(
            f"/ui/quantitative/studies/{study_id}/target-margins",
            data={
                "targets_json": json.dumps(
                    {"myord": {"1.0": 60, "2.0": 20, "3.0": 20}}
                )
            },
            follow_redirects=False,
        )
        study = self._study(study_id)
        self.client.post(
            f"/ui/quantitative/studies/{study_id}/weight-approval",
            data={
                "fingerprint": study.weight_set_record_id.rsplit(":", 1)[-1],
                "decision": "APPROVED",
                "rationale": "old dataset weighting",
            },
            follow_redirects=False,
        )
        return self._study(study_id)

    def test_same_content_replay_is_idempotent_and_different_upload_requires_intent(self):
        study_id, initial = self._create_with_sav("qu-replay")
        replay = self.client.post(
            f"/ui/quantitative/studies/{study_id}/dataset",
            files={
                "dataset": (
                    "renamed.sav",
                    sav_sample_bytes(),
                    "application/octet-stream",
                )
            },
            follow_redirects=False,
        )
        self.assertEqual(replay.status_code, 303)
        self.assertEqual(self._study(study_id), initial)
        datasets = self.container.quantitative_ui_service.state.list_for_run(
            study_id, project_id=study_id, expected_type=DatasetVersion
        )
        self.assertEqual(len(datasets), 1)

        ambiguous = self.client.post(
            f"/ui/quantitative/studies/{study_id}/dataset",
            files={"dataset": ("different.xlsx", self._replacement_bytes())},
        )
        self.assertEqual(ambiguous.status_code, 422)
        self.assertEqual(self._study(study_id), initial)

    def test_replacement_preserves_lineage_and_invalidates_all_current_authority(self):
        study_id, _ = self._create_with_sav("qu-authority")
        old = self._approved_old_authority(study_id)
        service = self.container.quantitative_ui_service
        old_dataset = service.state.load(
            old.dataset_record_id,
            project_id=study_id,
            expected_type=DatasetVersion,
        )
        old_weight = service.state.load(
            old.weight_set_record_id,
            project_id=study_id,
            expected_type=WeightSet,
        )

        self.assertEqual(self._replace(study_id).status_code, 303)
        current = self._study(study_id)
        current_dataset = service.state.load(
            current.dataset_record_id,
            project_id=study_id,
            expected_type=DatasetVersion,
        )
        self.assertEqual((current.project_id, current.run_id), (old.project_id, old.run_id))
        self.assertNotEqual(current_dataset.version_id, old_dataset.version_id)
        self.assertEqual(current_dataset.parent_version_id, old_dataset.version_id)
        self.assertEqual(
            current_dataset.parent_dataset_fingerprint,
            old_dataset.dataset_fingerprint,
        )
        self.assertEqual(current.state, "IMPORTED")
        self.assertIsNone(current.qc_record_id)
        self.assertIsNone(current.qc_approval_id)
        self.assertIsNone(current.target_plan_record_id)
        self.assertIsNone(current.weight_set_record_id)
        self.assertIsNone(current.weight_approval_id)
        self.assertIsNone(current.terminal_result_record_id)
        self.assertIs(
            self.container.workflow_service.get_workflow_run(study_id).status,
            WorkflowStatus.PAUSED,
        )
        self.assertFalse(
            self.container.worker_execution_service.process_once("qu-worker")
        )
        self.assertEqual(
            service.state.load(
                old.dataset_record_id,
                project_id=study_id,
                expected_type=DatasetVersion,
            ),
            old_dataset,
        )
        with self.assertRaises(QuantitativePersistenceError):
            validate_recovered_analysis_linkage(
                dataset=current_dataset, weight_set=old_weight
            )
        self.assertEqual(
            self.client.get(f"/ui/quantitative/studies/{study_id}/result.json").status_code,
            404,
        )

        self.client.post(
            f"/ui/quantitative/studies/{study_id}/qc", follow_redirects=False
        )
        new_qc = service.state.load(
            self._study(study_id).qc_record_id,
            project_id=study_id,
            expected_type=QualityControlRun,
        )
        with self.assertRaisesRegex(QuantitativeWorkflowError, "stale"):
            QuantitativeApprovalService(service.state, service.digest).require_current(
                old.qc_approval_id,
                project_id=study_id,
                subject_fingerprint=new_qc.fingerprint,
            )

    def test_restart_selects_new_current_version_and_replay_does_not_duplicate_it(self):
        study_id, _ = self._create_with_sav("qu-restart")
        self.assertEqual(self._replace(study_id).status_code, 303)
        current = self._study(study_id)
        service = self.container.quantitative_ui_service
        service._studies.clear()
        recovered = self._study(study_id)
        self.assertEqual(recovered, current)
        self.assertEqual(self._replace(study_id).status_code, 303)
        self.assertEqual(self._study(study_id), current)
        self.assertEqual(
            len(
                service.state.list_for_run(
                    study_id, project_id=study_id, expected_type=DatasetVersion
                )
            ),
            2,
        )

    def test_failed_replacement_preserves_previous_current_projection(self):
        study_id, initial = self._create_with_sav("qu-failure")
        malformed = self._replace(study_id, b"not-an-xlsx")
        self.assertEqual(malformed.status_code, 422)
        self.assertEqual(self._study(study_id), initial)

        service = self.container.quantitative_ui_service
        original_persist = service.state.persist

        def fail_new_dataset(value, **kwargs):
            if isinstance(value, DatasetVersion) and value.parent_version_id:
                raise RuntimeError("synthetic persistence failure")
            return original_persist(value, **kwargs)

        with patch.object(service.state, "persist", side_effect=fail_new_dataset):
            failed = self._replace(study_id)
        self.assertEqual(failed.status_code, 422)
        self.assertEqual(self._study(study_id), initial)

    def test_replacement_fails_closed_after_durable_execution_has_started(self):
        study_id, initial = self._create_with_sav("qu-started")
        run = self.container.workflow_service.get_workflow_run(study_id)
        run.tasks[0].ready()
        self.container.workflow_service.save_workflow_run(
            run,
            expected_version=self.container.workflow_service.get_workflow_run_version(
                study_id
            ),
            task_results={"safe": "authority"},
        )
        rejected = self._replace(study_id)
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(self._study(study_id), initial)

    def test_retry_after_projection_failure_reuses_partial_immutable_records(self):
        study_id, initial = self._create_with_sav("qu-partial-retry")
        service = self.container.quantitative_ui_service
        with patch.object(service, "_save", side_effect=RuntimeError("projection failure")):
            failed = self._replace(study_id)
        self.assertEqual(failed.status_code, 422)
        self.assertEqual(self._study(study_id), initial)

        retried = self._replace(study_id)
        self.assertEqual(retried.status_code, 303)
        current = self._study(study_id)
        self.assertNotEqual(current.dataset_record_id, initial.dataset_record_id)
        self.assertEqual(
            len(
                service.state.list_for_run(
                    study_id, project_id=study_id, expected_type=DatasetVersion
                )
            ),
            2,
        )

    def test_wrong_owner_cannot_replace(self):
        study_id, initial = self._create_with_sav("qu-owner")
        with self.assertRaisesRegex(ValueError, "not found"):
            self.container.quantitative_ui_service.upload(
                study_id,
                owner_id="foreign-owner",
                filename="replacement.xlsx",
                content=self._replacement_bytes(),
                replace_existing=True,
            )
        self.assertEqual(self._study(study_id), initial)


if __name__ == "__main__":
    unittest.main()

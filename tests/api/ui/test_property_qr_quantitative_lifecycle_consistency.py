from __future__ import annotations

from application.quantitative.state_persistence import decode_quantitative, encode_quantitative
from domain.quantitative.dataset import DatasetFormat, DatasetVersion
from domain.workflow_status import WorkflowStatus
from tests.api.helpers import ApiTestCase
from tests.application.quantitative.test_property_qa_byte_to_statistic_provenance import xlsx_bytes
from tests.fixtures.quantitative.sav_sample_fixture import sav_sample_bytes


class PropertyQrQuantitativeLifecycleConsistencyTests(ApiTestCase):
    def _create(self, key: str) -> str:
        response = self.client.post(
            "/ui/quantitative/studies",
            data={
                "title": "QR synthetic study",
                "description": "offline lifecycle acceptance",
                "submission_key": key,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        return response.headers["location"].rsplit("/", 1)[-1]

    def _principal_id(self) -> str:
        return self.container.authentication_service.authenticate_api_key(
            self.container._test_api_key_plaintext
        ).principal_id

    def test_create_and_upload_remain_paused_and_unclaimable(self):
        study_id = self._create("qr-paused")
        run = self.container.workflow_service.get_workflow_run(study_id)
        self.assertIs(run.status, WorkflowStatus.PAUSED)
        self.assertFalse(self.container.worker_execution_service.process_once("qr-worker"))

        uploaded = self.client.post(
            f"/ui/quantitative/studies/{study_id}/dataset",
            files={"dataset": ("sample.sav", sav_sample_bytes(), "application/octet-stream")},
            follow_redirects=False,
        )
        self.assertEqual(uploaded.status_code, 303)
        self.assertIs(
            self.container.workflow_service.get_workflow_run(study_id).status,
            WorkflowStatus.PAUSED,
        )
        self.assertFalse(self.container.worker_execution_service.process_once("qr-worker"))
        status = self.client.get(
            f"/ui/quantitative/studies/{study_id}/status.json"
        ).json()
        self.assertEqual(status["setup_state"], "IMPORTED")
        self.assertEqual(status["execution_status"], "paused")

    def _assert_format_reload(self, key, filename, content, expected):
        service = self.container.quantitative_ui_service
        owner_id = self._principal_id()
        study_id = self._create(f"qr-format-{key}")
        response = self.client.post(
            f"/ui/quantitative/studies/{study_id}/dataset",
            files={"dataset": (filename, content, "application/octet-stream")},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        service._studies.pop(study_id, None)
        recovered = service.get(study_id, owner_id=owner_id)
        dataset = service.state.load(
            recovered.dataset_record_id,
            project_id=recovered.project_id,
            expected_type=DatasetVersion,
        )
        self.assertIs(dataset.format, expected)
        page = self.client.get(f"/ui/quantitative/studies/{study_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(expected.value, page.text)

    def test_sav_reload_preserves_dataset_format_enum_and_renders(self):
        self._assert_format_reload(
            "sav", "sample.sav", sav_sample_bytes(), DatasetFormat.SAV
        )

    def test_legacy_plain_string_enums_reconstruct_at_persistence_boundary(self):
        study_id = self._create("qr-legacy-enum")
        self.client.post(
            f"/ui/quantitative/studies/{study_id}/dataset",
            files={"dataset": ("sample.sav", sav_sample_bytes(), "application/octet-stream")},
            follow_redirects=False,
        )
        service = self.container.quantitative_ui_service
        study = service.get(study_id, owner_id=self._principal_id())
        dataset = service.state.load(
            study.dataset_record_id,
            project_id=study.project_id,
            expected_type=DatasetVersion,
        )
        payload = encode_quantitative(dataset)
        payload["fields"]["format"] = dataset.format.value
        payload["fields"]["version_kind"] = dataset.version_kind.value
        payload["fields"]["pii_classification_status"] = (
            dataset.pii_classification_status.value
        )
        payload["fields"]["validation_status"] = dataset.validation_status.value
        recovered = decode_quantitative(payload)
        self.assertIs(recovered.format, DatasetFormat.SAV)
        self.assertIs(type(recovered.version_kind), type(dataset.version_kind))
        self.assertIs(
            type(recovered.pii_classification_status),
            type(dataset.pii_classification_status),
        )

    def test_xlsx_reload_preserves_dataset_format_enum_and_renders(self):
        self._assert_format_reload(
            "xlsx",
            "sample.xlsx",
            xlsx_bytes(["choice", "score"], [["A", 1], ["B", 2]]),
            DatasetFormat.XLSX,
        )

    def test_terminal_failure_is_exposed_alongside_setup_state(self):
        study_id = self._create("qr-failed-projection")
        self.client.post(
            f"/ui/quantitative/studies/{study_id}/dataset",
            files={"dataset": ("sample.sav", sav_sample_bytes(), "application/octet-stream")},
            follow_redirects=False,
        )
        run = self.container.workflow_service.get_workflow_run(study_id)
        run.resume()
        run.fail()
        self.container.workflow_service.save_workflow_run(
            run,
            expected_version=self.container.workflow_service.get_workflow_run_version(study_id),
        )
        status = self.client.get(
            f"/ui/quantitative/studies/{study_id}/status.json"
        ).json()
        self.assertEqual(status["setup_state"], "IMPORTED")
        self.assertEqual(status["execution_status"], "failed")
        page = self.client.get(f"/ui/quantitative/studies/{study_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Execution state: <strong>failed</strong>", page.text)
        self.assertNotIn("Run quality control", page.text)
        rejected = self.client.post(
            f"/ui/quantitative/studies/{study_id}/qc", follow_redirects=False
        )
        self.assertEqual(rejected.status_code, 422)

    def test_activation_is_owner_guarded_and_requires_completed_setup(self):
        study_id = self._create("qr-activation")
        service = self.container.quantitative_ui_service
        with self.assertRaisesRegex(ValueError, "not found"):
            service.resume_workflow(study_id, owner_id="foreign-owner")
        response = self.client.post(
            f"/ui/quantitative/studies/{study_id}/resume",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 422)
        self.assertIs(
            self.container.workflow_service.get_workflow_run(study_id).status,
            WorkflowStatus.PAUSED,
        )


if __name__ == "__main__":
    import unittest

    unittest.main()

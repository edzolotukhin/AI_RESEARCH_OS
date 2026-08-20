from __future__ import annotations

import unittest
import json

from tests.api.helpers import ApiTestCase
from tests.fixtures.quantitative.sav_sample_fixture import sav_sample_bytes


class PropertyQoQuantitativeUiVerticalTests(ApiTestCase):
    def _create(self, key: str = "qo-study-1"):
        response = self.client.post("/ui/quantitative/studies", data={
            "title": "Synthetic consumer survey", "description": "Offline QO acceptance",
            "submission_key": key,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        return response.headers["location"].rsplit("/", 1)[-1]

    def test_methodology_specific_create_is_idempotent_and_get_is_read_only(self):
        study_id = self._create()
        duplicate = self.client.post("/ui/quantitative/studies", data={
            "title": "Synthetic consumer survey", "description": "Offline QO acceptance",
            "submission_key": "qo-study-1",
        }, follow_redirects=False)
        self.assertEqual(duplicate.headers["location"].rsplit("/", 1)[-1], study_id)
        first = self.client.get(f"/ui/quantitative/studies/{study_id}/status.json").json()
        second = self.client.get(f"/ui/quantitative/studies/{study_id}/status.json").json()
        self.assertEqual(first, second)
        self.assertEqual(first["state"], "WAITING_FOR_DATASET")

    def test_real_sav_upload_and_safe_import_review(self):
        study_id = self._create("qo-upload")
        response = self.client.post(
            f"/ui/quantitative/studies/{study_id}/dataset",
            files={"dataset": ("sample.sav", sav_sample_bytes(), "application/octet-stream")},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        page = self.client.get(f"/ui/quantitative/studies/{study_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Safe import review", page.text)
        self.assertNotIn("protected-dataset://", page.text)
        self.assertNotIn("pseudonym", page.text.casefold())
        status = self.client.get(f"/ui/quantitative/studies/{study_id}/status.json").json()
        self.assertEqual(status["state"], "IMPORTED")

    def test_upload_failures_are_bounded_and_do_not_leak_exceptions(self):
        study_id = self._create("qo-bad-upload")
        for name, body in (("data.exe", b"x"), ("empty.sav", b""), ("broken.sav", b"not-sav")):
            response = self.client.post(
                f"/ui/quantitative/studies/{study_id}/dataset",
                files={"dataset": (name, body, "application/octet-stream")},
            )
            self.assertEqual(response.status_code, 422)
            self.assertNotIn("Traceback", response.text)
            self.assertNotIn("pyreadstat", response.text.casefold())

    def test_object_id_does_not_authorize_foreign_owner(self):
        study_id = self._create("qo-owner")
        service = self.container.quantitative_ui_service
        with self.assertRaises(ValueError):
            service.get(study_id, owner_id="foreign-principal")

    def test_qc_approval_is_fingerprint_bound_and_cannot_be_bypassed(self):
        study_id = self._create("qo-qc")
        self.client.post(
            f"/ui/quantitative/studies/{study_id}/dataset",
            files={"dataset": ("sample.sav", sav_sample_bytes(), "application/octet-stream")},
            follow_redirects=False,
        )
        qc_response = self.client.post(f"/ui/quantitative/studies/{study_id}/qc", follow_redirects=False)
        self.assertEqual(qc_response.status_code, 303)
        study = self.container.quantitative_ui_service.get(
            study_id, owner_id=self.container.authentication_service.authenticate_api_key(
                self.container._test_api_key_plaintext).principal_id)
        stale = self.client.post(f"/ui/quantitative/studies/{study_id}/qc-approval", data={
            "fingerprint": "stale", "decision": "APPROVED", "rationale": "wrong",
        })
        self.assertEqual(stale.status_code, 422)
        self.assertEqual(self.container.quantitative_ui_service.get(
            study_id, owner_id=self.container.authentication_service.authenticate_api_key(
                self.container._test_api_key_plaintext).principal_id).state, "AWAITING_QC_APPROVAL")
        accepted = self.client.post(f"/ui/quantitative/studies/{study_id}/qc-approval", data={
            "fingerprint": study.qc_record_id.rsplit(":", 1)[-1],
            "decision": "APPROVED", "rationale": "safe aggregate QC reviewed",
        }, follow_redirects=False)
        self.assertEqual(accepted.status_code, 303)

    def test_desk_entry_point_remains_separate(self):
        self.assertEqual(self.client.get("/ui/research/new").status_code, 200)
        self.assertEqual(self.client.get("/ui/quantitative/new").status_code, 200)

    def test_safe_study_projection_recovers_after_service_cache_loss(self):
        study_id = self._create("qo-recovery")
        service = self.container.quantitative_ui_service
        principal_id = self.container.authentication_service.authenticate_api_key(
            self.container._test_api_key_plaintext).principal_id
        expected = service.get(study_id, owner_id=principal_id)
        service._studies.clear()
        recovered = service.get(study_id, owner_id=principal_id)
        self.assertEqual(recovered, expected)

    def test_synthetic_sav_reaches_real_qm_qh_qj_qk_terminal_authority(self):
        study_id=self._create("qo-terminal")
        self.client.post(f"/ui/quantitative/studies/{study_id}/dataset",files={"dataset":("sample.sav",sav_sample_bytes(),"application/octet-stream")},follow_redirects=False)
        self.client.post(f"/ui/quantitative/studies/{study_id}/qc",follow_redirects=False)
        cleaned=self.client.post(f"/ui/quantitative/studies/{study_id}/cleaning",data={
            "variable_name":"mynum","replacements_json":json.dumps({"1.1":0,"1.2":7,"-1000.3":8,"-1.4":9,"1000.3":10})},follow_redirects=False)
        self.assertEqual(cleaned.status_code,303)
        service=self.container.quantitative_ui_service
        principal=self.container.authentication_service.authenticate_api_key(self.container._test_api_key_plaintext).principal_id
        study=service.get(study_id,owner_id=principal)
        self.client.post(f"/ui/quantitative/studies/{study_id}/qc-approval",data={"fingerprint":study.qc_record_id.rsplit(":",1)[-1],"decision":"APPROVED","rationale":"cleaned QC"},follow_redirects=False)
        weighted=self.client.post(f"/ui/quantitative/studies/{study_id}/target-margins",data={"targets_json":json.dumps({"myord":{"1.0":60,"2.0":20,"3.0":20}})},follow_redirects=False)
        self.assertEqual(weighted.status_code,303)
        study=service.get(study_id,owner_id=principal)
        approved=self.client.post(f"/ui/quantitative/studies/{study_id}/weight-approval",data={"fingerprint":study.weight_set_record_id.rsplit(":",1)[-1],"decision":"APPROVED","rationale":"diagnostics reviewed"},follow_redirects=False)
        self.assertEqual(approved.status_code,303)
        resumed=self.client.post(f"/ui/quantitative/studies/{study_id}/resume",follow_redirects=False)
        self.assertEqual(resumed.status_code,303)
        first=self.client.get(f"/ui/quantitative/studies/{study_id}/result.json")
        self.assertEqual(first.status_code,200)
        payload=first.json(); self.assertEqual(payload["terminal_status"],"COMPLETED")
        self.assertTrue(payload["statistics"]); self.assertTrue(payload["findings"]["accepted"]); self.assertTrue(payload["findings"]["rejected"])
        self.assertTrue(payload["insights"]["accepted"]); self.assertTrue(payload["insights"]["rejected"]); self.assertTrue(payload["report"]["sections"])
        records_before=len(service.state.list_for_run(study_id,project_id=study_id))
        duplicate=self.client.post(f"/ui/quantitative/studies/{study_id}/resume",follow_redirects=False)
        self.assertEqual(duplicate.status_code,303)
        second=self.client.get(f"/ui/quantitative/studies/{study_id}/result.json")
        self.assertEqual(second.json(),payload)
        self.assertEqual(len(service.state.list_for_run(study_id,project_id=study_id)),records_before)
        rendered=self.client.get(f"/ui/quantitative/studies/{study_id}").text
        for forbidden in ("protected-dataset://","pseudonym_bindings","AUTHORITATIVE_BUNDLE","Traceback"):
            self.assertNotIn(forbidden,rendered)


if __name__ == "__main__":
    unittest.main()

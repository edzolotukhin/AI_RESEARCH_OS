from __future__ import annotations

import re
import json
from pathlib import Path

from application.methods.quantitative.pin import METHOD_PIN, resolve_method_pin
from application.quantitative.workflow import (
    CMF_QUANTITATIVE_WORKFLOW_ID,
    QUANTITATIVE_WORKFLOW_ID,
)
from domain.quantitative.analysis_plan import QuantitativeAnalysisPlanVersion
from tests.api.helpers import ApiTestCase
from tests.application.quantitative.test_property_qa_byte_to_statistic_provenance import xlsx_bytes


class Qnt06bQuantAuthorityProductTests(ApiTestCase):
    def _owner(self):
        return self.container.authentication_service.authenticate_api_key(
            self.container._test_api_key_plaintext
        ).principal_id

    def _create(self, key="qnt06b"):
        response = self.client.post(
            "/ui/quantitative/studies",
            data={"title": "QNT-06B", "description": "Product flow", "submission_key": key},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        return response.headers["location"].rsplit("/", 1)[-1]

    def _upload_and_approve_qc(self, study_id, values=None):
        values = values or [[1], [2], [1], [2]]
        response = self.client.post(
            f"/ui/quantitative/studies/{study_id}/dataset",
            files={"dataset": ("known.xlsx", xlsx_bytes(["choice"], values),
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        response = self.client.post(f"/ui/quantitative/studies/{study_id}/qc", follow_redirects=False)
        self.assertEqual(response.status_code, 303, response.text)
        ui = self.container.quantitative_ui_service
        study = ui.get(study_id, owner_id=self._owner())
        page = self.client.get(f"/ui/quantitative/studies/{study_id}/data")
        self.assertEqual(page.status_code, 200)
        match = re.search(r'name="fingerprint" value="([^"]+)"', page.text)
        self.assertIsNotNone(match)
        response = self.client.post(
            f"/ui/quantitative/studies/{study_id}/qc-approval",
            data={"fingerprint": match.group(1), "decision": "APPROVED", "rationale": "Checked"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        return ui.get(study_id, owner_id=self._owner())

    def _upload_sav_and_approve_qc(self, study_id):
        response = self.client.post(
            f"/ui/quantitative/studies/{study_id}/dataset",
            files={"dataset": (
                "known.sav",
                Path("tests/fixtures/quantitative/rb_reconciliation.sav").read_bytes(),
                "application/octet-stream",
            )},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(self.client.post(
            f"/ui/quantitative/studies/{study_id}/qc", follow_redirects=False,
        ).status_code, 303)
        page = self.client.get(f"/ui/quantitative/studies/{study_id}/data")
        fingerprint = re.search(r'name="fingerprint" value="([^"]+)"', page.text)
        self.assertIsNotNone(fingerprint)
        response = self.client.post(
            f"/ui/quantitative/studies/{study_id}/qc-approval",
            data={"fingerprint": fingerprint.group(1), "decision": "APPROVED",
                  "rationale": "Known SAV reviewed"}, follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        return self.container.quantitative_ui_service.get(study_id, owner_id=self._owner())

    def test_product_creation_is_always_canonical_but_internal_legacy_reader_remains(self):
        self.container.quantitative_ui_service.cmf_quant_enabled = False
        study_id = self._create("canonical-with-flag-off")
        run = self.container.workflow_service.get_workflow_run(study_id)
        self.assertEqual(run.workflow_template_id, CMF_QUANTITATIVE_WORKFLOW_ID)
        pin = self.container.workflow_service.get_task_results(run.id)[METHOD_PIN]
        self.assertEqual(resolve_method_pin(pin, project_id=study_id, run_id=study_id).identity.version, "1")

        legacy = self.container.quantitative_ui_service.create_study(
            owner_id=self._owner(), title="Historical compatibility", description="",
            submission_key="explicit-internal-legacy", canonical=False,
        )
        self.assertEqual(
            self.container.workflow_service.get_workflow_run(legacy.run_id).workflow_template_id,
            QUANTITATIVE_WORKFLOW_ID,
        )

    def test_real_product_actions_reach_exact_approved_plan_without_execution(self):
        study_id = self._create("approved-authority")
        study = self._upload_and_approve_qc(study_id)
        _, codebook = self.container.quantitative_ui_service._dataset(study)
        variable = next(item for item in codebook.variables if item.analytically_eligible)
        configured = self.client.post(
            f"/ui/quantitative/studies/{study_id}/design",
            data={
                "title": "Known answer design", "research_question": "How is choice distributed?",
                "population": "Fixture respondents", "procedure": "ONE_WAY",
                "primary_variable_id": variable.variable_id, "weighting_mode": "UNWEIGHTED",
            },
            follow_redirects=False,
        )
        self.assertEqual(configured.status_code, 303, configured.text)
        page = self.client.get(f"/ui/quantitative/studies/{study_id}/analysis")
        self.assertEqual(page.status_code, 200)
        version = re.search(r'name="plan_version_id" value="([^"]+)"', page.text)
        fingerprint = re.search(r'name="expected_fingerprint" value="([^"]+)"', page.text)
        self.assertIsNotNone(version)
        self.assertIsNotNone(fingerprint)
        approved = self.client.post(
            f"/ui/quantitative/studies/{study_id}/design/approve",
            data={
                "plan_version_id": version.group(1),
                "expected_fingerprint": fingerprint.group(1),
                "rationale": "Exact dataset and procedure reviewed",
            },
            follow_redirects=False,
        )
        self.assertEqual(approved.status_code, 303, approved.text)
        authority = self.container.quantitative_authority_product_service.projection(
            study_id, owner_id=self._owner()
        )
        self.assertEqual(authority["design_state"], "APPROVED")
        self.assertEqual(authority["dataset_bound_version"], authority["dataset_version"])
        self.assertEqual(self.container.quantitative_ui_service.execution_status(
            study_id, owner_id=self._owner()), "paused")

    def test_unsupported_procedure_fails_closed_without_plan(self):
        study_id = self._create("unsupported")
        study = self._upload_and_approve_qc(study_id)
        _, codebook = self.container.quantitative_ui_service._dataset(study)
        response = self.client.post(
            f"/ui/quantitative/studies/{study_id}/design",
            data={"title": "Bad", "research_question": "Unsupported?", "population": "All",
                  "procedure": "REGRESSION", "primary_variable_id": codebook.variables[0].variable_id,
                  "weighting_mode": "UNWEIGHTED"},
        )
        self.assertEqual(response.status_code, 422)
        records = self.container.quantitative_ui_service.state.list_for_run(
            study.run_id, project_id=study.project_id
        )
        self.assertFalse(any(isinstance(item, QuantitativeAnalysisPlanVersion) for item in records))

    def test_weighted_design_requires_an_approved_exact_weight_authority(self):
        study_id = self._create("missing-weight-authority")
        study = self._upload_and_approve_qc(study_id)
        _, codebook = self.container.quantitative_ui_service._dataset(study)
        variable = next(item for item in codebook.variables if item.analytically_eligible)
        response = self.client.post(
            f"/ui/quantitative/studies/{study_id}/design",
            data={"title": "Weighted", "research_question": "Distribution?",
                  "population": "All", "procedure": "ONE_WAY",
                  "primary_variable_id": variable.variable_id,
                  "weighting_mode": "WEIGHTED"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("Approve a WeightSet", response.text)
        records = self.container.quantitative_ui_service.state.list_for_run(
            study.run_id, project_id=study.project_id
        )
        self.assertFalse(any(isinstance(item, QuantitativeAnalysisPlanVersion) for item in records))

    def test_approved_weightset_is_bound_exactly_to_weighted_design(self):
        study_id = self._create("approved-weight-authority")
        study = self._upload_sav_and_approve_qc(study_id)
        weighted = self.client.post(
            f"/ui/quantitative/studies/{study_id}/target-margins",
            data={"targets_json": json.dumps({"sex": {"1.0": 50, "2.0": 50}})},
            follow_redirects=False,
        )
        self.assertEqual(weighted.status_code, 303, weighted.text)
        page = self.client.get(f"/ui/quantitative/studies/{study_id}/data")
        fingerprint = re.search(r'name="fingerprint" value="([^"]+)"', page.text)
        self.assertIsNotNone(fingerprint)
        approved = self.client.post(
            f"/ui/quantitative/studies/{study_id}/weight-approval",
            data={"fingerprint": fingerprint.group(1), "decision": "APPROVED",
                  "rationale": "Weight diagnostics reviewed"}, follow_redirects=False,
        )
        self.assertEqual(approved.status_code, 303, approved.text)
        study = self.container.quantitative_ui_service.get(study_id, owner_id=self._owner())
        _, codebook = self.container.quantitative_ui_service._dataset(study)
        primary = next(item for item in codebook.variables if item.name == "categorical")
        configured = self.client.post(
            f"/ui/quantitative/studies/{study_id}/design",
            data={"title": "Weighted distribution", "research_question": "Distribution?",
                  "population": "Synthetic respondents", "procedure": "ONE_WAY",
                  "primary_variable_id": primary.variable_id, "weighting_mode": "WEIGHTED"},
            follow_redirects=False,
        )
        self.assertEqual(configured.status_code, 303, configured.text)
        authority = self.container.quantitative_authority_product_service.projection(
            study_id, owner_id=self._owner()
        )
        plan = self.container.quantitative_ui_service.state.load(
            authority["design_version"], project_id=study.project_id,
            expected_type=QuantitativeAnalysisPlanVersion,
        )
        self.assertTrue(all(item.weight_set_binding is not None for item in plan.planned_analyses))

    def test_supported_v1_cross_tab_and_comparisons_reach_design_review(self):
        cases = (
            ("CROSS_TAB", "categorical", "region", "", "", ""),
            ("INDEPENDENT_TWO_PROPORTION_Z_TEST", "categorical", "region", "1.0", "1.0", "2.0"),
            ("INDEPENDENT_WELCH_T_TEST", "numeric", "sex", "", "1.0", "2.0"),
        )
        for index, (procedure, primary_name, group_name, outcome, group_a, group_b) in enumerate(cases):
            with self.subTest(procedure=procedure):
                study_id = self._create(f"supported-{index}")
                study = self._upload_sav_and_approve_qc(study_id)
                _, codebook = self.container.quantitative_ui_service._dataset(study)
                variables = {item.name: item.variable_id for item in codebook.variables}
                response = self.client.post(
                    f"/ui/quantitative/studies/{study_id}/design",
                    data={"title": procedure, "research_question": "Supported analysis?",
                          "population": "Synthetic respondents", "procedure": procedure,
                          "primary_variable_id": variables[primary_name],
                          "group_variable_id": variables[group_name],
                          "outcome_category": outcome, "group_a_category": group_a,
                          "group_b_category": group_b, "weighting_mode": "UNWEIGHTED"},
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 303, response.text)
                authority = self.container.quantitative_authority_product_service.projection(
                    study_id, owner_id=self._owner()
                )
                self.assertEqual(authority["design_state"], "IN_REVIEW")

    def test_dataset_replacement_is_allowed_before_binding_and_rejected_after_binding(self):
        study_id = self._create("replacement")
        study = self._upload_and_approve_qc(study_id)
        first, _ = self.container.quantitative_ui_service._dataset(study)
        replaced = self.client.post(
            f"/ui/quantitative/studies/{study_id}/dataset",
            files={"dataset": ("new.xlsx", xlsx_bytes(["choice"], [[1], [1], [2]]),
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"replace_existing": "true"}, follow_redirects=False,
        )
        self.assertEqual(replaced.status_code, 303, replaced.text)
        study = self.container.quantitative_ui_service.get(study_id, owner_id=self._owner())
        second, codebook = self.container.quantitative_ui_service._dataset(study)
        self.assertNotEqual(first.version_id, second.version_id)
        study = self._upload_and_approve_qc(study_id, [[1], [1], [2]])
        variable = next(item for item in codebook.variables if item.analytically_eligible)
        self.client.post(
            f"/ui/quantitative/studies/{study_id}/design",
            data={"title": "Bound", "research_question": "Distribution?", "population": "All",
                  "procedure": "ONE_WAY", "primary_variable_id": variable.variable_id,
                  "weighting_mode": "UNWEIGHTED"}, follow_redirects=False,
        )
        rejected = self.client.post(
            f"/ui/quantitative/studies/{study_id}/dataset",
            files={"dataset": ("third.xlsx", xlsx_bytes(["choice"], [[2], [2], [2]]),
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"replace_existing": "true"},
        )
        self.assertEqual(rejected.status_code, 422)
        self.assertIn("unavailable after workflow execution begins", rejected.text)

    def test_foreign_plan_cannot_be_approved_for_another_study(self):
        first = self._create("first-scope")
        first_study = self._upload_and_approve_qc(first)
        _, first_codebook = self.container.quantitative_ui_service._dataset(first_study)
        self.client.post(
            f"/ui/quantitative/studies/{first}/design",
            data={"title": "First", "research_question": "First?", "population": "All",
                  "procedure": "ONE_WAY", "primary_variable_id": first_codebook.variables[0].variable_id,
                  "weighting_mode": "UNWEIGHTED"}, follow_redirects=False,
        )
        authority = self.container.quantitative_authority_product_service.projection(first, owner_id=self._owner())
        second = self._create("second-scope")
        self._upload_and_approve_qc(second)
        response = self.client.post(
            f"/ui/quantitative/studies/{second}/design/approve",
            data={"plan_version_id": authority["design_version"],
                  "expected_fingerprint": authority["design_approval_token"], "rationale": "wrong"},
        )
        self.assertEqual(response.status_code, 422)
